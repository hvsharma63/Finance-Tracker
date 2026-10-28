"""Mandatory financial acceptance tests A–H (master specification §20), via the HTTP API."""

from tests.helpers import (
    approve,
    balance,
    category_id,
    commit,
    create_account,
    import_csv,
    make_csv,
    rs,
    set_category,
    suggestions,
    summary,
    txns,
    upload,
)


def test_A_internal_transfer(client):
    src = create_account(client, "Savings A", opening=100000)
    dst = create_account(client, "Savings B", opening=10000)
    import_csv(client, src["id"], make_csv([("05/03/2026", "IMPS/P2A/509876543210/OWN A/C TRANSFER", 20000, None)]))
    import_csv(client, dst["id"], make_csv([("05/03/2026", "IMPS/509876543210/FROM SELF", None, 20000)]))
    sugg = suggestions(client)
    assert len(sugg) == 1 and sugg[0]["relationship_type"] == "transfer"
    assert any("Exact amount" in r for r in sugg[0]["matching_reason"]["reasons"])
    # Before approval nothing is assumed: both remain uncategorized, not income/expense
    s = summary(client)
    assert s["income"] == 0 and s["expenses"] == 0
    approve(client, sugg[0]["id"])
    assert balance(client, src["id"]) == rs(80000)
    assert balance(client, dst["id"]) == rs(30000)
    nw = client.get("/api/reports/net-worth").json()
    assert nw["groups"]["cash"] == rs(110000)
    s = summary(client)
    assert s["income"] == 0 and s["expenses"] == 0 and s["uncategorized_count"] == 0
    assert s["transfers_out"] == rs(20000) and s["transfers_in"] == rs(20000)
    # both source transactions are preserved
    assert len(txns(client)) == 2


def test_B_credit_card_repayment(client):
    bank = create_account(client, "Bank", opening=100000)
    card = create_account(client, "Card", account_type="credit_card", opening=0, masked="XX4321")
    card_csv = (b"Transaction Date,Transaction Details,Amount (INR)\n"
                b"03/03/2026,AMAZON PAY INDIA,15000.00\n"
                b"07/03/2026,ZOMATO,10000.00\n"
                b"12/03/2026,PAYMENT RECEIVED - THANK YOU,25000.00 Cr\n")
    b = upload(client, card["id"], card_csv, "card.csv", statement_type="credit_card")
    commit(client, b["id"])
    import_csv(client, bank["id"], make_csv([("10/03/2026", "BBPS/CREDIT CARD PAYMENT/XX4321", 25000, None)]))
    for t in txns(client, account_id=card["id"]):
        if t["amount_minor"] < 0:
            set_category(client, t["id"], "Shopping")
    sugg = suggestions(client)
    assert len(sugg) == 1 and sugg[0]["relationship_type"] == "card_payment"
    assert any("ending 4321" in r for r in sugg[0]["matching_reason"]["reasons"])
    approve(client, sugg[0]["id"])
    s = summary(client)
    assert s["expenses"] == rs(25000)  # purchases only, repayment not counted again
    assert s["card_repayments_paid"] == rs(25000)
    assert balance(client, card["id"]) == 0  # -25,000 purchases + 25,000 repayment
    assert balance(client, bank["id"]) == rs(75000)


def test_C_income_and_spending(client):
    bank = create_account(client, "Bank", opening=0)
    import_csv(client, bank["id"], make_csv([
        ("01/03/2026", "NEFT CR ACME PAYROLL SALARY", None, 100000),
        ("05/03/2026", "UPI/BIGBASKET", 15000, None),
        ("12/03/2026", "RENT MARCH", 25000, None),
    ]))
    t = {x["normalized_description"]: x for x in txns(client)}
    set_category(client, t["NEFT CR ACME PAYROLL SALARY"]["id"], "Salary")
    set_category(client, t["UPI/BIGBASKET"]["id"], "Groceries")
    set_category(client, t["RENT MARCH"]["id"], "Rent")
    s = summary(client)
    assert s["income"] == rs(100000)
    assert s["expenses"] == rs(40000)
    assert s["net_savings"] == rs(60000)


def test_D_investment_purchase(client):
    bank = create_account(client, "Bank", opening=100000)
    broker = create_account(client, "Mutual Funds", account_type="mutual_fund", opening=0)
    import_csv(client, bank["id"], make_csv([("10/03/2026", "ACH D- INDIAN CLEARING CORP MF SIP", 30000, None)]))
    bank_txn = txns(client)[0]
    inst = client.post("/api/investments/instruments", json={
        "name": "Synthetic Index Fund - Direct Growth", "instrument_type": "mutual_fund", "identifier": "INF000TEST01"}).json()
    r = client.post("/api/investments/transactions", json={
        "account_id": broker["id"], "instrument_id": inst["id"], "transaction_date": "2026-03-10",
        "transaction_type": "buy", "quantity": "1000.000", "unit_price": "30.00", "gross_amount_minor": rs(30000),
        "source_transaction_id": bank_txn["id"]})
    assert r.status_code == 201, r.text
    assert balance(client, bank["id"]) == rs(70000)
    pf = client.get("/api/investments/portfolio").json()
    assert pf["total_cost_basis_minor"] == rs(30000)
    s = summary(client)
    assert s["expenses"] == 0 and s["investment_contributions"] == rs(30000)
    nw = client.get("/api/reports/net-worth").json()
    assert nw["net_worth_minor"] == rs(100000)  # cash became an investment; no market change
    assert nw["groups"]["investments_at_cost_unvalued"] == rs(30000)
    assert nw["is_estimate"] is True  # because the holding has no valuation


def test_E_refund(client):
    card = create_account(client, "Card", account_type="credit_card", opening=0)
    data = (b"Date,Description,Amount\n"
            b"02/03/2026,AMAZON RETAIL ORDER,5000.00 Dr\n"
            b"09/03/2026,REFUND AMAZON RETAIL ORDER,1000.00 Cr\n")
    b = upload(client, card["id"], data, "card.csv", statement_type="credit_card")
    commit(client, b["id"])
    purchase = next(t for t in txns(client) if t["amount_minor"] < 0)
    set_category(client, purchase["id"], "Shopping")
    sugg = suggestions(client)
    assert len(sugg) == 1 and sugg[0]["relationship_type"] == "refund"
    approve(client, sugg[0]["id"])
    s = summary(client)
    assert s["expenses"] == rs(5000) and s["refunds"] == rs(1000)
    assert s["net_spending"] == rs(4000)
    assert s["income"] == 0  # refund is not earned income
    cats = client.get("/api/reports/categories", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    shopping = next(c for c in cats if c["category"] == "Shopping")
    assert shopping["net_minor"] == rs(4000)  # refund attributed to the original category


def test_F_duplicate_import(client):
    bank = create_account(client, "Bank", opening=1000)
    data = make_csv([
        ("01/03/2026", "UPI/TEA STALL", 20, None),
        ("01/03/2026", "UPI/TEA STALL", 20, None),  # legitimately identical second purchase
        ("02/03/2026", "UPI/GROCER", 500, None),
    ], opening=1000)
    first = import_csv(client, bank["id"], data)
    assert first["row_counts"]["accepted"] == 3  # identical tea purchases both kept
    bal = balance(client, bank["id"])
    second = upload(client, bank["id"], data)
    assert second["repeat_of_batch_id"] == first["id"]
    assert second["row_counts"]["exact_duplicates"] == 3 and second["row_counts"]["to_import"] == 0
    assert "already imported" in second["warnings"][0]
    done = commit(client, second["id"])
    assert done["row_counts"]["accepted"] == 0 and done["row_counts"]["duplicates_skipped"] == 3
    assert balance(client, bank["id"]) == bal
    assert len(txns(client)) == 3
    history = client.get("/api/imports").json()["items"]
    assert {h["id"] for h in history} == {first["id"], second["id"]}


def test_G_reconciliation_discrepancy(client):
    bank = create_account(client, "Bank")
    data = (b"Date,Narration,Withdrawal,Deposit,Balance\n"
            b",Opening Balance,,,10000.00\n"
            b"04/03/2026,ATM WDL,2000.00,,8000.00\n"
            b",Closing Balance,,,7500.00\n")
    b = upload(client, bank["id"], data)
    v = b["validation"]
    assert v["closing_balance_calculated"] == "8000.00"
    assert v["closing_balance_reported"] == "7500.00"
    assert v["closing_difference"] == "-500.00" and v["balance_check"] == "failed"
    commit(client, b["id"])
    stmts = client.get("/api/reconciliation/statements").json()
    assert stmts[0]["reconciliation_status"] == "discrepancy"
    assert stmts[0]["calculated_closing_minor"] == rs(8000)
    assert abs(stmts[0]["discrepancy_minor"]) == rs(500)
    # the transaction was not altered to force a match
    assert txns(client)[0]["amount_minor"] == -rs(2000)
    acct = client.get(f"/api/accounts/{bank['id']}").json()
    assert acct["reconciliation_status"] == "discrepancy"


def test_H_missing_investment_valuation(client):
    broker = create_account(client, "Demat", account_type="brokerage", opening=0)
    inst = client.post("/api/investments/instruments", json={
        "name": "Synthetic Industries Ltd", "instrument_type": "stock", "identifier": "INE000TEST01"}).json()
    client.post("/api/investments/transactions", json={
        "account_id": broker["id"], "instrument_id": inst["id"], "transaction_date": "2026-03-10",
        "transaction_type": "buy", "quantity": "10", "unit_price": "1500", "gross_amount_minor": rs(15000),
        "charges_minor": rs(20)})
    h = client.get("/api/investments/holdings").json()[0]
    assert h["cost_basis_minor"] == rs(15020)
    assert h["value_minor"] is None and h["value_known"] is False
    assert h["unit_price"] is None  # purchase price is not presented as a current price
    assert any("unknown" in w for w in h["warnings"])
    pf = client.get("/api/investments/portfolio").json()
    assert pf["known_value_minor"] == 0 and pf["unvalued_cost_basis_minor"] == rs(15020)
    assert pf["value_complete"] is False
    # once a dated valuation exists, it is used
    client.post("/api/investments/valuations", json={"instrument_id": inst["id"], "valuation_date": "2026-03-31",
                                                    "unit_price": "1600", "notes": "Manual check of exchange close"})
    h = client.get("/api/investments/holdings").json()[0]
    assert h["value_minor"] == rs(16000) and h["valuation_date"] == "2026-03-31"
    assert h["unrealized_gain_minor"] == rs(16000) - rs(15020)
    assert category_id(client, "Investment purchases")
