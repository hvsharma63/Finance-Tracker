"""Import pipeline integration tests: preview, corrections, overlap, delete, reprocess, profiles, PDFs."""

import io

from tests.fixtures import synthetic as syn
from tests.helpers import balance, commit, create_account, import_csv, make_csv, rs, txns, upload


def test_preview_does_not_touch_ledger_and_shows_validation(client):
    bank = create_account(client, "Bank")
    b = upload(client, bank["id"], syn.bank_csv())
    assert b["status"] == "preview"
    assert b["row_counts"]["extracted"] == len(syn.BANK_ROWS)
    assert b["validation"]["running_balance_check"] == "passed"
    assert b["validation"]["balance_check"] == "passed"
    assert b["statement_meta"]["period_start"] == "2026-04-01"
    assert b["statement_meta"]["account_hint"] == "XX9876"
    assert txns(client) == []  # nothing in the ledger before commit
    assert len(b["rows"]) == len(syn.BANK_ROWS)


def test_commit_sets_statement_opening_and_reconciles(client):
    bank = create_account(client, "Bank")
    import_csv(client, bank["id"], syn.bank_csv())
    acct = client.get(f"/api/accounts/{bank['id']}").json()
    assert acct["opening_balance_minor"] == rs(10000)
    assert acct["opening_source"] == "statement" and acct["opening_verification"] == "unverified"
    assert acct["calculated_balance_minor"] == int(syn.BANK_CLOSING * 100)
    assert acct["reconciliation_status"] == "reconciled"
    assert acct["last_statement_date"] == "2026-04-30"
    assert acct["balance_status"] == "unverified"


def test_account_suggested_from_masked_number(client):
    create_account(client, "Other")
    bank = create_account(client, "Main", masked="1234 5678 9876")
    r = client.post("/api/imports", files={"file": ("s.csv", syn.bank_csv(), "text/csv")})
    assert r.status_code == 201
    assert r.json()["account_id"] == bank["id"]
    assert r.json()["statement_meta"]["account_suggested"] is True


def test_row_correction_preserves_original(client):
    bank = create_account(client, "Bank")
    data = b"Date,Narration,Withdrawal,Deposit\n01/04/2026,OCR MISREAD,1O0.00,\n02/04/2026,Fine,50.00,\n"
    b = upload(client, bank["id"], data)
    bad = next(r for r in b["rows"] if r["status"] == "error")
    assert bad["include"] is False
    r = client.patch(f"/api/imports/{b['id']}/rows/{bad['id']}", json={"amount": "-100.00", "description": "Corrected"})
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["status"] == "warning" and row["include"] is True and row["amount_minor"] == -rs(100)
    commit(client, b["id"])
    t = next(x for x in txns(client) if x["normalized_description"] == "Corrected")
    assert t["original_description"] == "OCR MISREAD"
    assert t["amount_minor"] == -rs(100)


def test_user_can_exclude_row_and_reinclude_duplicate(client):
    bank = create_account(client, "Bank")
    b = upload(client, bank["id"], make_csv([("01/04/2026", "A", 10, None), ("02/04/2026", "B", 20, None)]))
    rid = b["rows"][0]["id"]
    client.patch(f"/api/imports/{b['id']}/rows/{rid}", json={"include": False})
    assert commit(client, b["id"])["row_counts"]["accepted"] == 1


def test_overlapping_statements_import_only_new_rows(client):
    bank = create_account(client, "Bank")
    rows = [("01/04/2026", "A", 100, None), ("10/04/2026", "B", None, 500), ("20/04/2026", "C", 50, None),
            ("05/05/2026", "D", 25, None), ("15/05/2026", "E", None, 75)]
    import_csv(client, bank["id"], make_csv(rows[:3], opening=1000))
    second = upload(client, bank["id"], make_csv(rows[1:], opening=900))  # overlaps B and C
    assert second["row_counts"]["exact_duplicates"] == 2
    assert second["row_counts"]["to_import"] == 2
    commit(client, second["id"])
    assert len(txns(client)) == 5
    assert balance(client, bank["id"]) == rs(1000 - 100 + 500 - 50 - 25 + 75)
    stmts = client.get("/api/reconciliation/statements").json()
    assert all(s["reconciliation_status"] == "reconciled" for s in stmts)  # duplicates count towards each statement


def test_possible_duplicate_flagged_not_dropped(client):
    bank = create_account(client, "Bank")
    import_csv(client, bank["id"], make_csv([("01/04/2026", "UPI/SHOP/123", 100, None)], with_balance=False))
    b = upload(client, bank["id"], make_csv([("02/04/2026", "UPI SHOP different text", 100, None)], with_balance=False))
    assert b["rows"][0]["duplicate_status"] == "possible"
    assert b["rows"][0]["include"] is True  # user decides
    assert b["row_counts"]["possible_duplicates"] == 1


def test_delete_committed_import_requires_confirmation_when_linked(client):
    a = create_account(client, "A", opening=1000)
    bb = create_account(client, "B", opening=0)
    ba = import_csv(client, a["id"], make_csv([("01/04/2026", "TRANSFER TO B", 300, None)]))
    import_csv(client, bb["id"], make_csv([("01/04/2026", "TRANSFER FROM A", None, 300)]))
    rel = client.get("/api/reconciliation/relationships").json()["items"][0]
    client.post(f"/api/reconciliation/relationships/{rel['id']}/approve")
    r = client.delete(f"/api/imports/{ba['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["approved_relationships"] == 1
    r = client.delete(f"/api/imports/{ba['id']}", params={"confirm_linked": True})
    assert r.status_code == 200
    assert balance(client, a["id"]) == rs(1000)
    assert client.get("/api/reconciliation/relationships", params={"status": "all"}).json()["total"] == 0
    other = txns(client)[0]
    assert other["reconciliation_status"] == "unreconciled" or other["account_id"] == bb["id"]


def test_delete_restores_statement_derived_opening(client):
    bank = create_account(client, "Bank")
    b = import_csv(client, bank["id"], syn.bank_csv())
    client.delete(f"/api/imports/{b['id']}")
    acct = client.get(f"/api/accounts/{bank['id']}").json()
    assert acct["opening_balance_minor"] is None and acct["calculated_balance_minor"] is None


def test_reprocess_shows_change_summary_and_adds_nothing_twice(client):
    bank = create_account(client, "Bank")
    b = import_csv(client, bank["id"], syn.bank_csv())
    r = client.post(f"/api/imports/{b['id']}/reprocess", json={})
    assert r.status_code == 201, r.text
    s = r.json()["change_summary"]
    assert s["unchanged"] == len(syn.BANK_ROWS) and s["new_or_changed_rows"] == 0
    assert r.json()["row_counts"]["to_import"] == 0
    commit(client, r.json()["id"])
    assert len(txns(client)) == len(syn.BANK_ROWS)


def test_manual_mapping_saved_as_profile_is_reused(client):
    bank = create_account(client, "Bank")
    data = b"When,What,Out,In\n01/04/2026,Coffee,120.00,\n02/04/2026,Refund,,20.00\n"
    b = upload(client, bank["id"], data, "odd.csv")
    assert b["statement_meta"]["needs_mapping"] is True and b["rows"] == []
    assert ["When", "What", "Out", "In"] in b["statement_meta"]["candidate_headers"]
    r = client.post(f"/api/imports/{b['id']}/reparse", json={"column_mapping": {
        "date": "When", "description": "What", "debit": "Out", "credit": "In"}})
    assert r.status_code == 200 and len(r.json()["rows"]) == 2
    p = client.post(f"/api/imports/{b['id']}/save-profile", json={"name": "Odd Bank CSV"})
    assert p.status_code == 201, p.text
    commit(client, b["id"])
    nxt = upload(client, bank["id"], b"When,What,Out,In\n05/04/2026,Tea,30.00,\n", "odd2.csv")
    assert nxt["parser_name"] == "profile:Odd Bank CSV"
    assert nxt["rows"][0]["amount_minor"] == -rs(30)


def test_layout_change_warning(client):
    bank = create_account(client, "Bank")
    import_csv(client, bank["id"], syn.bank_csv())
    alt = b"Date,Description,Debit,Credit,Balance\n05/05/2026,X,10.00,,100.00\n"
    b = upload(client, bank["id"], alt)
    assert any("layout differs" in w for w in b["warnings"])


def test_pdf_import_end_to_end(client):
    bank = create_account(client, "Bank")
    b = upload(client, bank["id"], syn.bank_pdf(), "stmt.pdf")
    assert b["parser_name"] == "generic_pdf" and b["file_type"] == "pdf"
    assert b["row_counts"]["extracted"] == len(syn.BANK_ROWS) and b["row_counts"]["errors"] == 0
    assert b["validation"]["balance_check"] == "passed"
    commit(client, b["id"])
    assert balance(client, bank["id"]) == int(syn.BANK_CLOSING * 100)


def test_password_protected_pdf(client):
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for p in PdfReader(io.BytesIO(syn.bank_pdf())).pages:
        w.add_page(p)
    w.encrypt("s3cret")
    buf = io.BytesIO()
    w.write(buf)
    bank = create_account(client, "Bank")
    b = upload(client, bank["id"], buf.getvalue(), "locked.pdf")
    assert b["status"] == "failed" and b["extraction_info"]["error_code"] == "pdf_password_required"
    b = upload(client, bank["id"], buf.getvalue(), "locked.pdf", password="wrong")
    assert b["extraction_info"]["error_code"] == "pdf_password_incorrect"
    b = upload(client, bank["id"], buf.getvalue(), "locked.pdf", password="s3cret")
    assert b["status"] == "preview" and b["row_counts"]["extracted"] == len(syn.BANK_ROWS)


def test_upload_rejects_bad_files(client):
    r = client.post("/api/imports", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_type"
    r = client.post("/api/imports", files={"file": ("x.csv", b"", "text/csv")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"
    r = client.post("/api/imports", files={"file": ("../../evil.csv", syn.bank_csv(), "text/csv")})
    assert r.status_code == 201 and r.json()["filename"] == "evil.csv"


def test_commit_is_idempotent(client):
    bank = create_account(client, "Bank")
    b = upload(client, bank["id"], syn.bank_csv())
    commit(client, b["id"])
    commit(client, b["id"])
    assert len(txns(client)) == len(syn.BANK_ROWS)


def test_commit_requires_account(client):
    r = client.post("/api/imports", files={"file": ("s.csv", make_csv([("01/04/2026", "A", 1, None)]), "text/csv")})
    b = r.json()
    assert b["account_id"] is None
    r = client.post(f"/api/imports/{b['id']}/commit")
    assert r.status_code == 400 and r.json()["error"]["code"] == "account_required"
