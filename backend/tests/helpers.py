"""Helpers for API-level tests."""

from __future__ import annotations

import csv
import io

INR = 100  # paise per rupee


def rs(rupees: int | float) -> int:
    return int(round(rupees * INR))


def make_csv(rows, opening=None, closing=None, period=None, with_balance=True) -> bytes:
    """rows: (date 'dd/mm/yyyy', description, withdrawal or None, deposit or None)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    if period:
        w.writerow([f"Statement Period: {period[0]} to {period[1]}"])
    hdr = ["Date", "Narration", "Withdrawal", "Deposit"] + (["Balance"] if with_balance else [])
    w.writerow(hdr)
    bal = opening
    if opening is not None:
        w.writerow(["", "Opening Balance", "", ""] + ([f"{opening:.2f}"] if with_balance else []))
    for d, desc, wd, dep in rows:
        if bal is not None:
            bal = bal - (wd or 0) + (dep or 0)
        w.writerow([d, desc, f"{wd:.2f}" if wd else "", f"{dep:.2f}" if dep else ""] +
                   ([f"{bal:.2f}" if bal is not None else ""] if with_balance else []))
    if closing is not None:
        w.writerow(["", "Closing Balance", "", ""] + ([f"{closing:.2f}"] if with_balance else []))
    return buf.getvalue().encode()


def create_account(client, name, account_type="savings", opening=None, opening_date=None, masked=None, verified=True):
    body = {"name": name, "account_type": account_type, "institution": "Synthetic Bank"}
    if opening is not None:
        body["opening_balance_minor"] = rs(opening)
        body["opening_date"] = opening_date or "2026-01-01"
        body["opening_verification"] = "verified" if verified else "unverified"
    if masked:
        body["masked_identifier"] = masked
    r = client.post("/api/accounts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, account_id, data: bytes, filename="stmt.csv", **form):
    files = {"file": (filename, data, "text/csv")}
    payload = {"account_id": str(account_id)} | {k: str(v) for k, v in form.items()}
    r = client.post("/api/imports", files=files, data=payload)
    assert r.status_code == 201, r.text
    return r.json()


def commit(client, batch_id):
    r = client.post(f"/api/imports/{batch_id}/commit")
    assert r.status_code == 200, r.text
    return r.json()


def import_csv(client, account_id, data: bytes, filename="stmt.csv"):
    b = upload(client, account_id, data, filename)
    assert b["status"] == "preview", b
    return commit(client, b["id"])


def category_id(client, name):
    cats = client.get("/api/categories").json()
    return next(c["id"] for c in cats if c["name"] == name)


def txns(client, **params):
    r = client.get("/api/transactions", params={"page_size": 500} | params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def set_category(client, txn_id, name):
    r = client.patch(f"/api/transactions/{txn_id}", json={"category_id": category_id(client, name)})
    assert r.status_code == 200, r.text
    return r.json()


def balance(client, account_id):
    return client.get(f"/api/accounts/{account_id}").json()["calculated_balance_minor"]


def summary(client, start="2026-01-01", end="2026-12-31"):
    return client.get("/api/reports/summary", params={"start": start, "end": end}).json()


def suggestions(client, status="suggested"):
    return client.get("/api/reconciliation/relationships", params={"status": status}).json()["items"]


def approve(client, rel_id, **body):
    r = client.post(f"/api/reconciliation/relationships/{rel_id}/approve", json=body or None)
    assert r.status_code == 200, r.text
    return r.json()
