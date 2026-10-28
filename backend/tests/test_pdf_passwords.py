"""Saved PDF passwords and institution parser integration through the import API."""

import io

from pypdf import PdfReader, PdfWriter

from tests.fixtures import bank_layouts as bl
from tests.helpers import commit, create_account, upload


def _encrypt(data: bytes, pw: str) -> bytes:
    w = PdfWriter()
    for p in PdfReader(io.BytesIO(data)).pages:
        w.add_page(p)
    w.encrypt(pw)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_entered_password_is_remembered_encrypted_and_reused(client, db):
    from app.models import PdfPassword

    card = create_account(client, "Neo", account_type="credit_card", masked="1111")
    pdf, _ = bl.axis_credit_card_pdf()
    locked = _encrypt(pdf, "TEST1234")
    b = upload(client, card["id"], locked, "neo.pdf", password="TEST1234")
    assert b["status"] == "preview" and b["parser_name"] == "axis_credit_card_pdf"
    assert any("remembered" in w for w in b["warnings"])
    saved = client.get("/api/pdf-passwords").json()
    assert len(saved) == 1 and saved[0]["label"] == "Axis Bank credit card" and "password" not in saved[0]
    row = db.query(PdfPassword).one()
    assert "TEST1234" not in row.secret_enc  # stored encrypted
    # next statement: no password typed, the saved one is used automatically
    b2 = upload(client, card["id"], locked, "neo2.pdf")
    assert b2["status"] == "preview" and b2["extraction_info"]["password"].startswith("saved:")
    assert any("saved password" in w for w in b2["warnings"])


def test_remember_can_be_declined_and_unknown_password_still_asks(client):
    pdf, _ = bl.rbl_credit_card_pdf()
    locked = _encrypt(pdf, "SECRET99")
    acct = create_account(client, "RBL", account_type="credit_card")
    b = upload(client, acct["id"], locked, "r.pdf", password="SECRET99", remember_password="false")
    assert b["status"] == "preview"
    assert client.get("/api/pdf-passwords").json() == []
    client.post("/api/pdf-passwords", json={"label": "Other bank", "password": "nope"})
    b = upload(client, acct["id"], locked, "r2.pdf")
    assert b["status"] == "failed" and b["extraction_info"]["error_code"] == "pdf_password_required"
    assert "none of the saved passwords" in b["error_message"]


def test_duplicate_password_saved_once_and_delete(client):
    for _ in range(2):
        assert client.post("/api/pdf-passwords", json={"label": "Axis", "password": "SAME"}).status_code == 201
    items = client.get("/api/pdf-passwords").json()
    assert len(items) == 1
    assert client.delete(f"/api/pdf-passwords/{items[0]['id']}").status_code == 200
    assert client.get("/api/pdf-passwords").json() == []


def test_short_card_suffix_suggests_matching_card_only(client):
    create_account(client, "Savings", masked="9933")
    card = create_account(client, "RBL BMS", account_type="credit_card", masked="5033")
    client.patch(f"/api/accounts/{card['id']}", json={"institution": "RBL Bank"})
    pdf, _ = bl.rbl_credit_card_pdf()  # statement shows only "...33"
    r = client.post("/api/imports", files={"file": ("rbl.pdf", pdf, "application/pdf")})
    assert r.json()["account_id"] == card["id"]


def test_institution_statement_imports_and_reconciles(client):
    acct = create_account(client, "SBI")
    pdf, exp = bl.sbi_savings_pdf()
    b = upload(client, acct["id"], pdf, "sbi.pdf")
    assert b["parser_name"] == "sbi_savings_pdf" and b["validation"]["running_balance_check"] == "passed"
    commit(client, b["id"])
    a = client.get(f"/api/accounts/{acct['id']}").json()
    assert a["reconciliation_status"] == "reconciled"
    assert a["calculated_balance_minor"] == int(exp["closing"] * 100)
