"""Reconciliation workflow and categorization rules."""

from tests.helpers import (
    approve,
    balance,
    category_id,
    create_account,
    import_csv,
    make_csv,
    rs,
    set_category,
    suggestions,
    summary,
    txns,
)


def _pair(client, amount_out=50000, amount_in=50000, days=0, desc_out="NEFT TO SELF", desc_in="NEFT FROM SELF"):
    a = create_account(client, "A", opening=100000)
    b = create_account(client, "B", opening=0)
    import_csv(client, a["id"], make_csv([("01/04/2026", desc_out, amount_out, None)]))
    import_csv(client, b["id"], make_csv([(f"{1 + days:02d}/04/2026", desc_in, None, amount_in)]))
    return a, b


def test_no_suggestion_outside_window(client):
    _pair(client, days=9)
    assert suggestions(client) == []


def test_window_is_configurable(client):
    client.patch("/api/settings", json={"values": {"matching_window_days": 10}})
    _pair(client, days=9)
    assert len(suggestions(client)) == 1


def test_reject_is_remembered(client):
    _pair(client)
    s = suggestions(client)[0]
    client.post(f"/api/reconciliation/relationships/{s['id']}/reject")
    client.post("/api/reconciliation/suggest")
    assert suggestions(client) == []
    assert suggestions(client, "rejected")[0]["id"] == s["id"]


def test_undo_restores_classification(client):
    a, _ = _pair(client)
    s = suggestions(client)[0]
    approve(client, s["id"])
    assert summary(client)["uncategorized_count"] == 0
    r = client.post(f"/api/reconciliation/relationships/{s['id']}/undo")
    assert r.status_code == 200 and r.json()["review_status"] == "undone"
    assert summary(client)["uncategorized_count"] == 2
    assert all(t["reconciliation_status"] == "unreconciled" for t in txns(client))
    approve(client, s["id"])  # can be re-approved
    assert balance(client, a["id"]) == rs(50000)


def test_partial_transfer_with_fee_tolerance(client):
    client.patch("/api/settings", json={"values": {"matching_amount_tolerance_minor": rs(25)}})
    _pair(client, amount_out=50000, amount_in=49990)
    s = suggestions(client)[0]
    assert s["matched_amount_minor"] == rs(49990)
    assert s["matching_reason"]["amount_difference_minor"] == -rs(10)
    approve(client, s["id"])
    out = next(t for t in txns(client) if t["amount_minor"] < 0)
    full = client.get(f"/api/transactions/{out['id']}").json()
    parts = {p["class"]: p["amount_minor"] for p in full["reporting_parts"]}
    assert parts == {"transfer": -rs(49990), "uncategorized": -rs(10)}  # unmatched difference stays visible


def test_split_transfer_to_two_accounts_and_over_allocation(client):
    a = create_account(client, "A", opening=100000)
    b = create_account(client, "B", opening=0)
    c = create_account(client, "C", opening=0)
    import_csv(client, a["id"], make_csv([("01/04/2026", "BULK TRANSFER", 50000, None)]))
    import_csv(client, b["id"], make_csv([("01/04/2026", "FROM A", None, 30000)]))
    import_csv(client, c["id"], make_csv([("01/04/2026", "FROM A", None, 20000)]))
    out = next(t for t in txns(client) if t["amount_minor"] < 0)
    tb = next(t for t in txns(client) if t["account_id"] == b["id"])
    tc = next(t for t in txns(client) if t["account_id"] == c["id"])
    r1 = client.post("/api/reconciliation/relationships", json={"source_transaction_id": out["id"],
                     "related_transaction_id": tb["id"], "relationship_type": "transfer", "matched_amount_minor": rs(30000)})
    r2 = client.post("/api/reconciliation/relationships", json={"source_transaction_id": out["id"],
                     "related_transaction_id": tc["id"], "relationship_type": "transfer", "matched_amount_minor": rs(20000)})
    assert r1.status_code == 201 and r2.status_code == 201, (r1.text, r2.text)
    s = summary(client)
    assert s["transfers_out"] == rs(50000) and s["uncategorized_count"] == 0
    r3 = client.post("/api/reconciliation/relationships", json={"source_transaction_id": out["id"],
                     "related_transaction_id": tb["id"], "relationship_type": "investment_contribution",
                     "matched_amount_minor": rs(1)})
    assert r3.status_code == 409  # would over-allocate


def test_transfer_must_be_opposite_signs(client):
    a = create_account(client, "A", opening=0)
    b = create_account(client, "B", opening=0)
    import_csv(client, a["id"], make_csv([("01/04/2026", "X", 100, None)]))
    import_csv(client, b["id"], make_csv([("01/04/2026", "Y", 100, None)]))
    t1, t2 = txns(client)
    r = client.post("/api/reconciliation/relationships", json={"source_transaction_id": t1["id"],
                    "related_transaction_id": t2["id"], "relationship_type": "transfer"})
    assert r.status_code == 400


def test_mark_duplicate_removes_from_ledger(client):
    a = create_account(client, "A", opening=1000)
    import_csv(client, a["id"], make_csv([("01/04/2026", "SHOP ONE", 100, None)], with_balance=False))
    import_csv(client, a["id"], make_csv([("01/04/2026", "SHOP 1 (other export)", 100, None)], with_balance=False),
               "second.csv")
    t1, t2 = sorted(txns(client), key=lambda t: t["id"])
    assert balance(client, a["id"]) == rs(800)
    r = client.post("/api/reconciliation/mark-duplicate", json={"original_transaction_id": t1["id"],
                                                                "duplicate_transaction_id": t2["id"]})
    assert r.status_code == 200, r.text
    assert balance(client, a["id"]) == rs(900)
    client.post(f"/api/reconciliation/relationships/{r.json()['id']}/undo")
    assert balance(client, a["id"]) == rs(800)


def test_rules_priority_user_override_and_reapply(client):
    a = create_account(client, "A", opening=0)
    groceries, food = category_id(client, "Groceries"), category_id(client, "Food delivery")
    client.post("/api/rules", json={"name": "swiggy instamart", "priority": 10, "category_id": groceries,
                                    "conditions": {"match": "all", "conditions": [
                                        {"field": "description", "op": "contains", "value": "instamart"}]}})
    client.post("/api/rules", json={"name": "swiggy", "priority": 20, "category_id": food,
                                    "conditions": {"match": "all", "conditions": [
                                        {"field": "description", "op": "contains", "value": "swiggy"},
                                        {"field": "direction", "op": "equals", "value": "debit"}]}})
    import_csv(client, a["id"], make_csv([("01/04/2026", "UPI/SWIGGY INSTAMART", 300, None),
                                          ("02/04/2026", "UPI/SWIGGY", 450, None),
                                          ("03/04/2026", "UPI/SWIGGY REFUND", None, 50)]))
    by = {t["normalized_description"]: t for t in txns(client)}
    assert by["UPI/SWIGGY INSTAMART"]["category_id"] == groceries
    assert by["UPI/SWIGGY"]["category_id"] == food and by["UPI/SWIGGY"]["category_source"] == "rule"
    assert by["UPI/SWIGGY REFUND"]["category_id"] is None  # direction condition
    out = set_category(client, by["UPI/SWIGGY"]["id"], "Restaurants")
    assert out["rule_suggestion"]["conditions"]["conditions"]
    client.post("/api/rules/reapply")
    assert next(t for t in txns(client) if t["id"] == by["UPI/SWIGGY"]["id"])["category_name"] == "Restaurants"
    hist = client.get(f"/api/transactions/{by['UPI/SWIGGY']['id']}").json()["history"]
    assert hist and hist[-1]["action"] == "updated"


def test_invalid_rule_rejected(client):
    r = client.post("/api/rules", json={"name": "bad", "category_id": category_id(client, "Rent"),
                                        "conditions": {"match": "all", "conditions": [
                                            {"field": "description", "op": "regex", "value": "("}]}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_rule"


def test_review_queue_and_bulk(client):
    a = create_account(client, "A", opening=0)
    import_csv(client, a["id"], make_csv([("01/04/2026", "X", 1, None), ("02/04/2026", "Y", 2, None)]))
    q = client.get("/api/transactions/review-queue").json()
    assert q["total"] == 2
    ids = [t["id"] for t in q["items"]]
    client.post("/api/transactions/bulk-categorize", json={"transaction_ids": ids, "category_id": category_id(client, "Shopping")})
    assert client.get("/api/transactions/review-queue").json()["total"] == 0
    assert summary(client)["expenses"] == rs(3)


def test_search_filter_sort_paginate(client):
    a = create_account(client, "A", opening=0)
    import_csv(client, a["id"], make_csv([(f"{d:02d}/04/2026", f"ITEM {d}", d * 10, None) for d in range(1, 21)]))
    r = client.get("/api/transactions", params={"q": "ITEM 1", "sort": "amount", "order": "asc", "page_size": 5}).json()
    assert r["total"] == 11  # ITEM 1, 10-19
    assert r["items"][0]["amount_minor"] == -rs(190)
    r = client.get("/api/transactions", params={"start": "2026-04-05", "end": "2026-04-06"}).json()
    assert r["total"] == 2
    r = client.get("/api/transactions", params={"min_amount": rs(150)}).json()
    assert r["total"] == 6
    r = client.get("/api/transactions", params={"reporting_class": "uncategorized", "page_size": 3}).json()
    assert r["total"] == 20 and len(r["items"]) == 3
