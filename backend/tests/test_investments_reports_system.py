"""Investments, reports, exports, budgets, backup/restore, auth and security."""

import io
import zipfile

import openpyxl

from tests.helpers import category_id, create_account, import_csv, make_csv, rs, set_category, txns


def _inst(client, ident="INE000TEST02", itype="stock"):
    return client.post("/api/investments/instruments", json={"name": f"Test {ident}", "instrument_type": itype,
                                                            "identifier": ident}).json()


def _inv(client, acct, inst, d, typ, qty=None, amount=0, charges=0, ratio=None):
    body = {"account_id": acct, "instrument_id": inst, "transaction_date": d, "transaction_type": typ,
            "gross_amount_minor": amount, "charges_minor": charges}
    if qty is not None:
        body["quantity"] = str(qty)
    if ratio is not None:
        body["split_ratio"] = str(ratio)
    r = client.post("/api/investments/transactions", json=body)
    assert r.status_code == 201, r.text


def test_weighted_average_cost_sell_split_bonus_dividend(client):
    acct = create_account(client, "Demat", account_type="brokerage", opening=0)["id"]
    i = _inst(client)["id"]
    _inv(client, acct, i, "2026-01-05", "buy", 10, rs(1000), rs(10))   # cost 1010
    _inv(client, acct, i, "2026-01-10", "buy", 10, rs(1200))           # cost 2210, qty 20, avg 110.5
    _inv(client, acct, i, "2026-02-01", "sell", 5, rs(750), rs(5))     # remove 552.5 -> 553 (half-up); gain 745-552.50
    h = client.get("/api/investments/holdings").json()[0]
    assert h["quantity"] == "15"
    assert h["cost_basis_minor"] == 221000 - 55250
    assert h["realized_gain_minor"] == (75000 - 500) - 55250
    _inv(client, acct, i, "2026-03-01", "split", ratio=2)
    _inv(client, acct, i, "2026-03-05", "bonus", 10)
    _inv(client, acct, i, "2026-03-10", "dividend", amount=rs(80))
    h = client.get("/api/investments/holdings").json()[0]
    assert h["quantity"] == "40"
    assert h["cost_basis_minor"] == 221000 - 55250  # split and bonus do not change cost
    assert h["dividends_minor"] == rs(80)
    pf = client.get("/api/investments/portfolio").json()
    assert pf["realized_gain_minor"] == (75000 - 500) - 55250


def test_sell_everything_closes_position(client):
    acct = create_account(client, "Demat", account_type="brokerage", opening=0)["id"]
    i = _inst(client)["id"]
    _inv(client, acct, i, "2026-01-05", "buy", 3, rs(300))
    _inv(client, acct, i, "2026-01-06", "sell", 3, rs(330))
    assert client.get("/api/investments/holdings").json() == []
    pf = client.get("/api/investments/portfolio").json()
    assert pf["closed_positions"][0]["realized_gain_minor"] == rs(30)


def test_investment_csv_import_preview_then_commit_idempotent(client):
    acct = create_account(client, "MF", account_type="mutual_fund", opening=0)["id"]
    data = (b"Date,ISIN,Scheme Name,Transaction Type,Units,NAV,Amount\n"
            b"05/01/2026,INF000TEST09,Test Flexi Cap Direct,SIP Purchase,100.000,50.00,5000.00\n"
            b"05/02/2026,INF000TEST09,Test Flexi Cap Direct,SIP Purchase,98.039,51.00,5000.00\n"
            b"10/02/2026,INF000TEST09,Test Flexi Cap Direct,Mystery,1,1,1\n")
    files = {"file": ("mf.csv", data, "text/csv")}
    r = client.post("/api/investments/import", files=files, data={"account_id": acct, "kind": "transactions", "dry_run": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 2 and len(r.json()["errors"]) == 1
    assert client.get("/api/investments/holdings").json() == []  # dry run changed nothing
    r = client.post("/api/investments/import", files={"file": ("mf.csv", data, "text/csv")},
                    data={"account_id": acct, "kind": "transactions", "dry_run": "false"})
    assert r.json()["created"] == 2
    r = client.post("/api/investments/import", files={"file": ("mf.csv", data, "text/csv")},
                    data={"account_id": acct, "kind": "transactions", "dry_run": "false"})
    assert r.json()["created"] == 0 and r.json()["skipped_duplicates"] == 2
    nav = b"NAV Date,ISIN,NAV\n31/03/2026,INF000TEST09,55.1234\n"
    r = client.post("/api/investments/import", files={"file": ("nav.csv", nav, "text/csv")},
                    data={"account_id": acct, "kind": "valuations", "dry_run": "false"})
    assert r.json()["created"] == 1, r.text
    h = client.get("/api/investments/holdings").json()[0]
    assert h["quantity"] == "198.039" and h["valuation_date"] == "2026-03-31"
    assert h["value_minor"] == round(198.039 * 55.1234 * 100)


def test_fixed_deposit_values(client):
    fd_acct = create_account(client, "FD 1", account_type="fixed_deposit")["id"]
    r = client.post("/api/investments/fixed-deposits", json={
        "account_id": fd_acct, "principal_minor": rs(100000), "opening_date": "2026-01-01",
        "maturity_date": "2027-01-01", "interest_rate": "7.25", "reported_maturity_value_minor": rs(107450)})
    assert r.status_code == 201, r.text
    nw = client.get("/api/reports/net-worth").json()
    line = next(a for a in nw["accounts"] if a["account_id"] == fd_acct)
    assert line["balance_minor"] == rs(100000) and line["basis"] == "principal" and nw["is_estimate"]
    fd = client.get("/api/investments/portfolio").json()["fixed_deposits"][0]
    assert fd["projected_interest_minor"] == rs(7450) and fd["credited_interest_minor"] == 0


def test_cash_flow_and_exports(client):
    bank = create_account(client, "Bank", opening=10000, opening_date="2026-03-01")
    import_csv(client, bank["id"], make_csv([("01/04/2026", "SALARY", None, 50000), ("02/04/2026", "RENT", 20000, None),
                                             ("03/04/2026", "ATM WDL", 3000, None)]))
    t = {x["normalized_description"]: x["id"] for x in txns(client)}
    set_category(client, t["SALARY"], "Salary")
    set_category(client, t["RENT"], "Rent")
    set_category(client, t["ATM WDL"], "Cash withdrawals")
    cf = client.get("/api/reports/cash-flow", params={"start": "2026-04-01", "end": "2026-04-30"}).json()
    assert cf["opening_cash_minor"] == rs(10000) and cf["closing_cash_minor"] == rs(37000)
    assert cf["income_minor"] == rs(50000) and cf["expenses_minor"] == -rs(20000)
    assert cf["cash_withdrawals_minor"] == -rs(3000) and cf["check"] is True
    r = client.get("/api/transactions/export", params={"fmt": "csv"})
    assert r.status_code == 200 and "SALARY" in r.content.decode("utf-8-sig")
    r = client.get("/api/reports/export/categories", params={"fmt": "xlsx", "start": "2026-04-01", "end": "2026-04-30"})
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    rows = list(wb.active.values)
    assert rows[1][1] == "Rent" and float(rows[1][-1]) == 20000.0
    r = client.get("/api/reports/export/monthly", params={"fmt": "csv", "start": "2026-04-01", "end": "2026-04-30"})
    assert r.status_code == 200


def test_csv_export_neutralises_formulas(client):
    bank = create_account(client, "Bank", opening=0)
    import_csv(client, bank["id"], make_csv([("01/04/2026", "=HYPERLINK(evil)", 1, None)]))
    body = client.get("/api/transactions/export").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body


def test_budget_status(client):
    bank = create_account(client, "Bank", opening=0)
    import_csv(client, bank["id"], make_csv([("01/04/2026", "BIGBASKET", 4000, None)]))
    set_category(client, txns(client)[0]["id"], "Groceries")
    r = client.post("/api/budgets", json={"category_id": category_id(client, "Groceries"), "amount_minor": rs(10000)})
    assert r.status_code == 201
    s = client.get("/api/budgets/status", params={"month": "2026-04-01"}).json()["items"][0]
    assert s["spent_minor"] == rs(4000) and s["remaining_minor"] == rs(6000) and s["percent_used"] == 40.0


def test_recurring_candidates_are_suggestions_only(client):
    from datetime import timedelta

    from app.services.reporting.reports import today

    bank = create_account(client, "Bank", opening=10000)
    base = today() - timedelta(days=100)
    rows = [((base + timedelta(days=30 * k)).strftime("%d/%m/%Y"), "NETFLIX SUBSCRIPTION", 649, None) for k in range(4)]
    import_csv(client, bank["id"], make_csv(rows))
    before = len(txns(client))
    c = client.get("/api/reports/recurring-candidates").json()
    assert c and c[0]["cadence"] == "monthly" and c[0]["typical_amount_minor"] == rs(649)
    r = client.post("/api/recurring", json={"name": "Netflix", "match_key": c[0]["match_key"],
                                           "expected_amount_minor": rs(649), "cadence": "monthly"})
    assert r.status_code == 201
    assert len(txns(client)) == before  # no fictional future transactions


def test_dashboard_from_ledger(client):
    r = client.get("/api/reports/dashboard").json()
    assert r["has_data"] is False and r["cards"]["net_worth_minor"] == 0
    bank = create_account(client, "Bank", opening=5000)
    import_csv(client, bank["id"], make_csv([("01/04/2026", "X", 1000, None)]))
    r = client.get("/api/reports/dashboard").json()
    assert r["has_data"] and r["cards"]["cash_minor"] == rs(4000)
    assert r["balances"][0]["coverage_end"] == "2026-04-01"


def test_backup_and_restore_round_trip(client):
    bank = create_account(client, "Bank", opening=1000)
    import_csv(client, bank["id"], make_csv([("01/04/2026", "BEFORE BACKUP", 100, None)]))
    r = client.post("/api/backups", json={})
    assert r.status_code == 201, r.text
    name = r.json()["filename"]
    assert r.json()["details"]["tables"]["transactions"] == 1 and r.json()["details"]["documents"] == 1
    data = client.get(f"/api/backups/{name}/download").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "manifest.json" in z.namelist()
    # change data after the backup
    import_csv(client, bank["id"], make_csv([("02/04/2026", "AFTER BACKUP", 200, None)]), "b.csv")
    create_account(client, "Extra")
    r = client.post("/api/backups/restore", data={"filename": name})
    assert r.status_code == 400 and r.json()["error"]["code"] == "confirmation_required"
    r = client.post("/api/backups/restore", data={"filename": name, "confirm": "true"})
    assert r.status_code == 200, r.text
    assert [t["normalized_description"] for t in txns(client)] == ["BEFORE BACKUP"]
    assert [a["name"] for a in client.get("/api/accounts").json()] == ["Bank"]
    # sequences were reset: new rows get fresh ids
    assert create_account(client, "After restore")["id"] > bank["id"]
    # tampered backup is rejected
    bad = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z, zipfile.ZipFile(buf := io.BytesIO(), "w") as out:
        for n in z.namelist():
            content = z.read(n)
            out.writestr(n, content.replace(b"BEFORE BACKUP", b"TAMPERED") if n.endswith("transactions.json") else content)
    r = client.post("/api/backups/restore", files={"file": ("b.zip", buf.getvalue(), "application/zip")},
                    data={"confirm": "true"})
    assert r.status_code == 400 and "Checksum" in r.json()["error"]["message"]
    del bad


def test_csrf_header_required(client):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as raw:
        r = raw.post("/api/accounts", json={"name": "x", "account_type": "savings"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
        assert raw.get("/api/health").json()["status"] == "ok"


def test_auth_flow_and_rate_limit(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), headers={"X-Requested-With": "finance-tracker"}) as c:
            assert c.get("/api/accounts").status_code == 401
            assert c.get("/api/auth/status").json()["setup_required"] is True
            assert c.post("/api/auth/setup", json={"username": "me", "password": "short"}).status_code == 400
            r = c.post("/api/auth/setup", json={"username": "me", "password": "a-long-password"})
            assert r.status_code == 200
            assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
            assert c.get("/api/accounts").status_code == 200
            assert c.post("/api/auth/setup", json={"username": "x", "password": "a-long-password"}).status_code == 409
            c.post("/api/auth/logout")
            assert c.get("/api/accounts").status_code == 401
            codes = [c.post("/api/auth/login", json={"username": "me", "password": "wrong-password"}).status_code
                     for _ in range(6)]
            assert codes[:5] == [401] * 5 and codes[5] == 429
    finally:
        monkeypatch.setenv("AUTH_ENABLED", "false")
        get_settings.cache_clear()


def test_security_headers_and_error_shape(client):
    r = client.get("/api/accounts/999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    r = client.post("/api/accounts", json={"name": "x", "account_type": "nonsense"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_document_retention_keeps_ledger(client, db):
    from datetime import datetime, timedelta, timezone

    from app.models import ImportBatch
    from app.services.imports import storage
    from app.services.imports.retention import purge_old_documents

    bank = create_account(client, "Bank", opening=0)
    b = import_csv(client, bank["id"], make_csv([("01/04/2026", "OLD", 10, None)]))
    batch = db.get(ImportBatch, b["id"])
    path = storage.resolve(batch.storage_reference)
    assert path.exists()
    batch.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    db.commit()
    assert purge_old_documents(db, 365) == 1
    assert not path.exists()
    assert len(txns(client)) == 1  # ledger untouched
    assert client.get(f"/api/imports/{b['id']}").json()["has_file"] is False


def test_cli_backup(capsys):
    from app.cli import main

    assert main(["backup"]) == 0
    assert "Backup written" in capsys.readouterr().out
