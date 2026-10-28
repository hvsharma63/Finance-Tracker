/** Formatting only — no arithmetic on money beyond display. Amounts arrive as integer paise. */

export function inr(minor: number | null | undefined, opts: { sign?: boolean; compact?: boolean } = {}): string {
  if (minor === null || minor === undefined) return "—";
  const neg = minor < 0;
  const abs = Math.abs(minor);
  if (opts.compact && abs >= 100_000_00) {
    const lakhs = abs / 100 / 100_000;
    const s = lakhs >= 100 ? `${(lakhs / 100).toFixed(2)} Cr` : `${lakhs.toFixed(2)} L`;
    return `${neg ? "-" : opts.sign ? "+" : ""}₹${s}`;
  }
  const rupees = Math.floor(abs / 100);
  const paise = String(abs % 100).padStart(2, "0");
  const s = String(rupees);
  let grouped = s;
  if (s.length > 3) {
    const head = s.slice(0, -3);
    const tail = s.slice(-3);
    grouped = head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail;
  }
  return `${neg ? "-" : opts.sign && minor > 0 ? "+" : ""}₹${grouped}.${paise}`;
}

/** Parse a user-entered rupee amount ("1,23,456.78", "-500") into paise without floats. */
export function parseRupees(input: string): number | null {
  const s = input.replace(/[₹,\s]/g, "").trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  const neg = s.startsWith("-");
  const [whole, frac = ""] = s.replace("-", "").split(".");
  const v = Number(whole) * 100 + Number(frac.padEnd(2, "0"));
  return neg ? -v : v;
}

export function minorToInput(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "";
  const neg = minor < 0;
  const abs = Math.abs(minor);
  return `${neg ? "-" : ""}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
}

export function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS[Number(m) - 1]} ${y.slice(2)}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
}

export function todayIso(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function monthStartIso(iso = todayIso()): string {
  return iso.slice(0, 8) + "01";
}

export function daysAgoIso(days: number): string {
  const d = new Date(todayIso());
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  savings: "Savings", current: "Current", cash: "Cash", credit_card: "Credit card", fixed_deposit: "Fixed deposit",
  brokerage: "Brokerage / demat", mutual_fund: "Mutual funds", investment_other: "Other investment", loan: "Loan",
  liability_other: "Other liability", custom_asset: "Custom asset",
};

export const CLASS_LABELS: Record<string, string> = {
  income: "Income", expense: "Expense", refund: "Refund", transfer: "Transfer", card_payment: "Card repayment",
  investment: "Investment", loan_principal: "Loan principal", cash_withdrawal: "Cash withdrawal",
  excluded: "Excluded", uncategorized: "Uncategorized",
};

export const REL_LABELS: Record<string, string> = {
  transfer: "Internal transfer", card_payment: "Card repayment", refund: "Refund", duplicate: "Duplicate",
  investment_contribution: "Investment contribution", investment_withdrawal: "Investment withdrawal",
  loan_payment: "Loan payment", split: "Split", fee: "Fee", other: "Other",
};
