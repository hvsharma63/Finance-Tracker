import { expect, type Page, test } from "@playwright/test";

/* Synthetic statements — no real data. */
const csv = (lines: string[]) => Buffer.from(lines.join("\n") + "\n");
const BANK_1 = csv([
  "Synthetic Bank Ltd - Statement",
  "Account No: XXXXXXXX9876",
  "Statement Period: 01/04/2026 to 15/04/2026",
  "Date,Narration,Withdrawal,Deposit,Balance",
  ",Opening Balance,,,100000.00",
  "02/04/2026,NEFT CR ACME PAYROLL SALARY,,100000.00,200000.00",
  "05/04/2026,UPI/BIGBASKET/412345678999,2500.00,,197500.00",
  "10/04/2026,BBPS/CREDIT CARD PAYMENT/XX4321,25000.00,,172500.00",
  "12/04/2026,IMPS/P2A/509876543210/OWN TRANSFER,20000.00,,152500.00",
  ",Closing Balance,,,152500.00",
]);
const BANK_2 = csv([
  "Account No: XXXXXXXX9876",
  "Statement Period: 10/04/2026 to 30/04/2026",
  "Date,Narration,Withdrawal,Deposit,Balance",
  ",Opening Balance,,,197500.00",
  "10/04/2026,BBPS/CREDIT CARD PAYMENT/XX4321,25000.00,,172500.00",
  "12/04/2026,IMPS/P2A/509876543210/OWN TRANSFER,20000.00,,152500.00",
  "20/04/2026,UPI/ZOMATO/412345670000,800.00,,151700.00",
  ",Closing Balance,,,151700.00",
]);
const SECOND = csv(["Date,Narration,Withdrawal,Deposit,Balance", ",Opening Balance,,,0.00",
  "12/04/2026,IMPS/509876543210/FROM SELF,,20000.00,20000.00"]);
const CARD = csv(["Synthetic Card Services - Credit Card Statement", "Card No: XXXX XXXX XXXX 4321",
  "Transaction Date,Transaction Details,Amount (INR)",
  "03/04/2026,AMAZON PAY INDIA,15000.00", "07/04/2026,FLIPKART INTERNET,10000.00",
  "10/04/2026,PAYMENT RECEIVED - THANK YOU,25000.00 Cr"]);

const H = { "X-Requested-With": "finance-tracker" };

async function upload(page: Page, name: string, data: Buffer, opts: { account?: string; type?: string } = {}) {
  await page.goto("/import");
  await page.getByLabel("Statement file").setInputFiles({ name, mimeType: "text/csv", buffer: data });
  if (opts.account) await page.getByLabel("Account").selectOption({ label: opts.account });
  if (opts.type) await page.getByLabel("Statement type").selectOption(opts.type);
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page).toHaveURL(/\/import\/\d+/);
}

async function commit(page: Page) {
  await page.getByRole("button", { name: /Confirm import of/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByText(/Imported \d+ transaction/)).toBeVisible();
}

test("complete personal finance workflow", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  test.info().annotations.push({ type: "page-errors", description: "see end of test" });
  // First run: create the single user
  await page.goto("/");
  await page.getByLabel("Username").fill("e2e");
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Confirm password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("No financial data yet")).toBeVisible();

  // Create an account through the UI
  await page.getByRole("button", { name: "Add an account" }).click();
  await page.getByRole("button", { name: "New account" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Account name").fill("E2E Savings");
  await dlg.getByLabel("Institution").fill("Synthetic Bank");
  await dlg.getByLabel(/Last 4 digits/).fill("9876");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("link", { name: "E2E Savings" })).toBeVisible();
  // Remaining accounts via the API (same session cookie)
  for (const body of [
    { name: "E2E Card", account_type: "credit_card", masked_identifier: "4321", opening_balance_minor: 0, opening_date: "2026-04-01" },
    { name: "E2E Second", account_type: "savings" },
    { name: "E2E Funds", account_type: "mutual_fund", opening_balance_minor: 0, opening_date: "2026-04-01" },
  ]) expect((await page.request.post("/api/accounts", { data: body, headers: H })).status()).toBe(201);

  // Upload, review and commit the first bank statement (account detected from XX9876)
  await upload(page, "bank-apr-1.csv", BANK_1);
  await expect(page.getByLabel("Import into")).toHaveValue(/\d+/);
  await expect(page.getByText(/Suggested from the account number/)).toBeVisible();
  await expect(page.getByText("UPI/BIGBASKET/412345678999")).toBeVisible();
  await expect(page.getByRole("row", { name: /Running balance chain/ }).or(page.getByText("Running balance chain"))).toBeVisible();
  await commit(page);

  // Correct a category and accept the rule suggestion
  await page.goto("/transactions");
  await page.getByRole("button", { name: "UPI/BIGBASKET/412345678999" }).click();
  const td = page.getByRole("dialog");
  await td.getByLabel("Category").selectOption({ label: "Groceries" });
  await td.getByRole("button", { name: "Save changes" }).click();
  await td.getByRole("button", { name: "Create rule" }).click();
  await td.getByRole("button", { name: "Close" }).first().click();
  await expect(page.getByRole("row", { name: /BIGBASKET/ }).getByText("Groceries")).toBeVisible();

  // Overlapping statement: only the new row is imported
  await upload(page, "bank-apr-2.csv", BANK_2);
  await expect(page.getByText("Duplicate of #", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm import of 1 transaction(s)" })).toBeVisible();
  await commit(page);

  await upload(page, "second.csv", SECOND, { account: "E2E Second (Savings)" });
  await commit(page);
  await upload(page, "card.csv", CARD, { account: "E2E Card (Credit card)", type: "credit_card" });
  await commit(page);

  // Review and approve suggested matches (transfer + card repayment)
  await page.goto("/reconciliation");
  await expect(page.getByText("Internal transfer")).toBeVisible();
  await expect(page.getByText("Card repayment")).toBeVisible();
  const approveButtons = page.getByRole("button", { name: "Approve", exact: true });
  await expect(approveButtons).toHaveCount(2);
  await approveButtons.first().click();
  await expect(approveButtons).toHaveCount(1);
  await approveButtons.first().click();
  await expect(page.getByText("No suggestions to review")).toBeVisible();

  // Dashboard reflects the ledger: 1,51,700 + 20,000 cash; card fully repaid
  await page.goto("/");
  await expect(page.getByText("Bank & cash balances").locator("..")).toContainText("₹1,71,700.00");
  await expect(page.getByText("Credit card outstanding").locator("..")).toContainText("₹0.00");

  // Investment holding with no valuation shows value unknown
  const inst = await (await page.request.post("/api/investments/instruments", { headers: H,
    data: { name: "E2E Index Fund", instrument_type: "mutual_fund", identifier: "INF000E2E001" } })).json();
  const accts = await (await page.request.get("/api/accounts")).json();
  const funds = accts.find((a: { name: string }) => a.name === "E2E Funds");
  const buy = await page.request.post("/api/investments/transactions", { headers: H, data: { account_id: funds.id, instrument_id: inst.id,
    transaction_date: "2026-04-15", transaction_type: "buy", quantity: "100", unit_price: "100", gross_amount_minor: 1000000 } });
  expect(buy.status(), await buy.text()).toBe(201);
  await page.goto("/investments");
  await expect(page.getByText("E2E Index Fund").first(), pageErrors.join(" | ")).toBeVisible();
  await expect(page.getByText("unknown").first()).toBeVisible();

  // Export a report
  await page.goto("/reports");
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Excel" }).click()]);
  expect(dl.suggestedFilename()).toMatch(/\.xlsx$/);

  // Backup, then restore it
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Backups" }).click();
  await page.getByRole("button", { name: "Create backup now" }).click();
  await expect(page.getByText(/created and verified/)).toBeVisible();
  await page.getByRole("button", { name: "Restore…" }).first().click();
  await page.getByRole("button", { name: "Replace all data" }).click();
  // Restore clears sessions: sign in again and confirm data survived
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Username").fill("e2e");
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByText("Bank & cash balances").locator("..")).toContainText("₹1,71,700.00");
});
