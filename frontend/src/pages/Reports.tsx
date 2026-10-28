import { useQuery } from "@tanstack/react-query";
import { Download, Printer } from "lucide-react";
import { useState } from "react";
import { type Range, RangeFilter } from "@/components/RangeFilter";
import { Button, Card, ErrorBox, Money, PageHeader, Spinner, Status, Table } from "@/components/ui";
import { api, download } from "@/lib/api";
import { ACCOUNT_TYPE_LABELS, fmtDate, monthStartIso, todayIso } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */
const EXPORTS: [string, string][] = [["summary", "Summary"], ["monthly", "Monthly"], ["categories", "Spending categories"], ["income", "Income"],
  ["merchants", "Merchants"], ["cash-flow", "Cash flow"], ["net-worth", "Net worth"], ["accounts", "Accounts"], ["largest", "Largest expenses"]];

export default function Reports() {
  const [r, setR] = useState<Range>({ start: monthStartIso(), end: todayIso() });
  const p = { start: r.start, end: r.end };
  const cf = useQuery({ queryKey: ["cash-flow", p], queryFn: () => api.get<any>("/reports/cash-flow", p) });
  const nw = useQuery({ queryKey: ["net-worth", r.end], queryFn: () => api.get<any>("/reports/net-worth", { as_of: r.end }) });
  const accts = useQuery({ queryKey: ["accounts-report"], queryFn: () => api.get<any[]>("/reports/accounts") });
  const [kind, setKind] = useState("categories");
  const c = cf.data;

  return (
    <>
      <PageHeader title="Reports" description="Printable and exportable. All figures come from the ledger."
        actions={<>
          <select aria-label="Report to export" className="h-9 rounded-md border border-border bg-surface px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
            {EXPORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <Button onClick={() => download(`/reports/export/${kind}`, { ...p, fmt: "csv" })}><Download className="h-4 w-4" />CSV</Button>
          <Button onClick={() => download(`/reports/export/${kind}`, { ...p, fmt: "xlsx" })}><Download className="h-4 w-4" />Excel</Button>
          <Button onClick={() => window.print()}><Printer className="h-4 w-4" />Print / PDF</Button>
        </>} />
      <RangeFilter value={r} onChange={setR} accounts={false} />
      <p className="mb-3 hidden text-sm print:block">Period {fmtDate(r.start)} – {fmtDate(r.end)}</p>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Cash flow" subtitle="Savings, current and cash accounts">
          {cf.isLoading ? <Spinner /> : cf.isError ? <ErrorBox error={cf.error} /> : (
            <Table><tbody>
              <tr><td>Opening cash</td><td className="text-right font-medium">{c.opening_cash_minor == null ? "unknown" : <Money minor={c.opening_cash_minor} />}</td></tr>
              <tr><td>Income</td><td className="text-right"><Money minor={c.income_minor} colored /></td></tr>
              <tr><td>Expenses</td><td className="text-right"><Money minor={c.expenses_minor} colored /></td></tr>
              <tr><td>Refunds</td><td className="text-right"><Money minor={c.refunds_minor} colored /></td></tr>
              <tr><td>Transfers between own accounts</td><td className="text-right"><Money minor={c.transfers_minor} colored /></td></tr>
              <tr><td>Credit card repayments</td><td className="text-right"><Money minor={c.card_repayments_minor} colored /></td></tr>
              <tr><td>Investment contributions / withdrawals</td><td className="text-right"><Money minor={c.investment_flows_minor} colored /></td></tr>
              <tr><td>Loan flows</td><td className="text-right"><Money minor={c.loan_flows_minor} colored /></td></tr>
              <tr><td>Cash withdrawals</td><td className="text-right"><Money minor={c.cash_withdrawals_minor} colored /></td></tr>
              <tr><td>Uncategorized & other</td><td className="text-right"><Money minor={c.uncategorized_minor + c.excluded_minor} colored /></td></tr>
              <tr><td className="font-semibold">Closing cash</td><td className="text-right font-semibold">{c.closing_cash_minor == null ? "unknown" : <Money minor={c.closing_cash_minor} />}</td></tr>
            </tbody></Table>
          )}
          {c?.accounts_with_unknown_opening?.length > 0 && <p className="mt-2 text-xs text-warning">Opening/closing unknown because these accounts have no opening balance: {c.accounts_with_unknown_opening.join(", ")}.</p>}
          {c?.check === true && <p className="mt-2 text-xs text-subtle">Check: opening + movements = closing ✓</p>}
        </Card>

        <Card title={`Net worth as of ${fmtDate(r.end)}`} subtitle="Liabilities shown as amounts owed">
          {nw.isLoading ? <Spinner /> : nw.data && <>
            <Table><tbody>
              {Object.entries(nw.data.groups as Record<string, number>).map(([k, v]) => (
                <tr key={k}><td className="capitalize">{k.replace(/_/g, " ")}</td><td className="text-right"><Money minor={["credit_cards", "loans", "other_liabilities"].includes(k) ? -v : v} /></td></tr>))}
              <tr><td className="font-semibold">Total assets</td><td className="text-right font-semibold"><Money minor={nw.data.total_assets_minor} /></td></tr>
              <tr><td className="font-semibold">Total liabilities</td><td className="text-right font-semibold"><Money minor={nw.data.total_liabilities_minor} /></td></tr>
              <tr><td className="font-semibold">Net worth{nw.data.is_estimate && " (estimate)"}</td><td className="text-right text-base font-semibold"><Money minor={nw.data.net_worth_minor} /></td></tr>
            </tbody></Table>
            <ul className="mt-2 list-disc pl-4 text-xs text-subtle">{nw.data.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>
          </>}
        </Card>
      </div>

      <Card title="Accounts" className="mt-4">
        <Table>
          <thead><tr><th>Account</th><th>Type</th><th className="text-right">Calculated balance</th><th className="text-right">Last statement balance</th><th>Last statement</th><th>Reconciliation</th><th>Unmatched?</th></tr></thead>
          <tbody>{accts.data?.map((a) => (
            <tr key={a.account_id}><td>{a.name}</td><td>{ACCOUNT_TYPE_LABELS[a.account_type]}</td><td className="text-right"><Money minor={a.calculated_balance_minor} /></td>
              <td className="text-right"><Money minor={a.last_statement_balance_minor} /></td><td>{fmtDate(a.last_statement_date)}</td>
              <td><Status status={a.reconciliation_status} /></td><td>{a.has_unreconciled ? "Yes" : "No"}</td></tr>))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
