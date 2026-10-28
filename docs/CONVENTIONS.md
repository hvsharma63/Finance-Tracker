# Financial conventions

These definitions are implemented in `backend/app/core/money.py` and
`backend/app/services/reporting/classification.py` and are used everywhere.

## Money

* Amounts are stored as **integer minor units** (`BIGINT`, paise for INR). ₹1,234.50 = `123450`.
* Parsing uses `decimal.Decimal`; floats are never used for money.
* Investment quantities and unit prices use `NUMERIC(24, 8)` / `Decimal`.
* Rounding (only where unavoidable, e.g. average cost of a partial sale) is ROUND_HALF_UP to 1 paisa.

## Sign convention (holder perspective) — the same for every account type

`amount_minor` is signed from **your** point of view:

| Movement | Sign |
|---|---|
| Money arrives in a bank/cash account | **+** |
| Money leaves a bank/cash account | **−** |
| Credit-card purchase, fee, interest (you owe more) | **−** |
| Credit-card payment, refund, cashback (you owe less) | **+** |
| Loan disbursement into the loan account (you owe more) | **−** |
| Loan repayment received by the loan account | **+** |

So an account's **balance = opening balance + Σ amount_minor** and is:

* positive for assets you hold,
* negative for liabilities (a card with ₹25,000 due has balance −₹25,000; the UI shows
  "Outstanding ₹25,000").

**Net worth = Σ all account balances + investment holdings value.** Transfers between
your own accounts sum to zero and therefore never change net worth.

Parsers must translate each statement's own convention (Dr/Cr, "Withdrawal/Deposit",
card "amount due") into this convention. A sign is never flipped to make a balance
reconcile.

## Balances

| Term | Meaning |
|---|---|
| Statement-reported balance | Closing balance printed on the latest imported statement, with its date. |
| Calculated balance | Opening balance + all committed movements. Only "verified" if the opening balance is verified. |
| Reconciled balance | Calculated balance at a statement end date that equals the reported closing balance. |
| Estimated / incomplete | Opening balance unknown, or gaps in statement coverage. |
| Coverage through | Last date covered by an imported statement. Balances are "as of" this date, never "current". |

## Reporting classes

Every transaction resolves to one reporting class, in this order:

1. If it is part of an **approved relationship** of type `transfer`, `card_payment`,
   `investment_contribution`, `investment_withdrawal` or `loan_payment`, its class is that
   financial movement.
2. If it is linked as a **refund/reversal** of a purchase, its class is `refund` and it reduces
   the original purchase's category.
3. Otherwise its **category's `reporting_type`**: `income`, `expense`, `transfer`,
   `investment`, `loan_principal`, `refund`, `cash_withdrawal`, `excluded`.
4. Otherwise `uncategorized`. Uncategorized movements are **not** guessed into income or
   expenses by sign; they are reported separately and listed in the review queue.

## Report definitions

* **Income** = Σ amount of `income` class transactions (excludes transfers, loan proceeds,
  investment principal, card repayments, refunds).
* **Expenses (gross)** = Σ (−amount) of `expense` class transactions.
* **Refunds** = Σ amount of `refund` class transactions.
* **Net spending** = Expenses − Refunds.
* **Net savings** = Income − Net spending.
* **Investment contributions** = Σ (−amount) of `investment` / `investment_contribution`
  outflows from cash accounts; reported separately, never as spending.
* **Cash withdrawals** (ATM) are a separate `cash_withdrawal` class, shown in cash flow as
  "other cash movements", not as spending (spending from cash is unknown). Change the
  category's reporting type if you prefer to treat them as spending.
* **Spending coverage** is incomplete when a credit card has repayments in the period but no
  imported card statement covering it.

## Investments

* Cost basis: **weighted average cost** per (account, instrument). Buy charges are added to
  cost; sell charges reduce proceeds.
* Splits multiply quantity, keep cost. Bonus issues add quantity at zero cost.
* Value = quantity × latest dated valuation (statement, imported NAV/price or manual entry).
  If none exists the value is **unknown**. Cost basis is never shown as market value.
* Net worth shows investments with unknown valuation as a separate, labelled
  "at cost — no valuation" line; the total is then flagged as an estimate.
