import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTable, GRID, Legend, MoneyTooltip, SERIES, axisProps, compactInr } from "@/components/charts";
import { type Range, RangeFilter } from "@/components/RangeFilter";
import { Button, Card, ErrorBox, Money, Notice, PageHeader, Spinner, Stat, Table } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { fmtDate, fmtMonth, inr, monthStartIso, todayIso } from "@/lib/format";
import { useMut } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function SpendingIncome() {
  const [r, setR] = useState<Range>({ start: monthStartIso(), end: todayIso() });
  const p = { start: r.start, end: r.end, account_id: r.account_id };
  const summary = useQuery({ queryKey: ["summary", p], queryFn: () => api.get<any>("/reports/summary", p) });
  const cats = useQuery({ queryKey: ["cats", p], queryFn: () => api.get<any[]>("/reports/categories", p) });
  const income = useQuery({ queryKey: ["income", p], queryFn: () => api.get<any[]>("/reports/categories", { ...p, kind: "income" }) });
  const merchants = useQuery({ queryKey: ["merchants", p], queryFn: () => api.get<any[]>("/reports/merchants", p) });
  const largest = useQuery({ queryKey: ["largest", p], queryFn: () => api.get<any[]>("/reports/largest", p) });
  const unusual = useQuery({ queryKey: ["unusual", p], queryFn: () => api.get<any[]>("/reports/unusual", p) });
  const monthly = useQuery({ queryKey: ["monthly-12", r.account_id], queryFn: () => api.get<any[]>("/reports/monthly", { account_id: r.account_id }) });
  const recurring = useQuery({ queryKey: ["recurring-cands"], queryFn: () => api.get<any[]>("/reports/recurring-candidates") });
  const confirmed = useQuery({ queryKey: ["recurring"], queryFn: () => api.get<any[]>("/recurring") });
  const confirm = useMut((c: any) => api.post("/recurring", { name: c.name, match_key: c.match_key, account_id: c.account_id,
    category_id: c.category_id, expected_amount_minor: c.typical_amount_minor, cadence: c.cadence, typical_day: c.typical_day, last_seen_date: c.last_date }));
  const s = summary.data;
  const link = (extra: Record<string, unknown>) => `/transactions${qs({ start: r.start, end: r.end, account_id: r.account_id, ...extra } as any)}`;
  const confirmedKeys = new Set(confirmed.data?.map((c) => c.match_key));

  return (
    <>
      <PageHeader title="Spending & Income" description="Transfers, card repayments and investment principal are excluded from income and spending." />
      <RangeFilter value={r} onChange={setR} />
      {summary.isError && <ErrorBox error={summary.error} />}
      {s && <>
        {s.coverage_warnings?.map((w: string) => <div key={w} className="mb-2"><Notice tone="info">{w}</Notice></div>)}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Link to={link({ reporting_class: "income" })}><Stat label="Income" value={inr(s.income)} /></Link>
          <Link to={link({ reporting_class: "expense" })}><Stat label="Expenses (gross)" value={inr(s.expenses)} /></Link>
          <Link to={link({ reporting_class: "refund" })}><Stat label="Refunds & reversals" value={inr(s.refunds)} /></Link>
          <Stat label="Net spending" value={inr(s.net_spending)} />
          <Stat label="Net savings" value={<span className={s.net_savings < 0 ? "text-negative" : ""}>{inr(s.net_savings)}</span>}
            sub={s.income ? `${Math.round((s.net_savings / s.income) * 100)}% of income` : undefined} />
          <Stat label="Investment contributions" value={inr(s.investment_contributions)} sub={`Withdrawals ${inr(s.investment_withdrawals)}`} />
          <Stat label="Transfers between own accounts" value={inr(s.transfers_out)} />
          <Stat label="Card repayments" value={inr(s.card_repayments_paid)} />
          <Stat label="Cash withdrawals" value={inr(s.cash_withdrawals)} sub="Not counted as spending" />
          <Link to={link({ reporting_class: "uncategorized" })}><Stat label="Uncategorized" value={`${s.uncategorized_count} txns`}
            sub={`Out ${inr(s.uncategorized_out)} · In ${inr(s.uncategorized_in)}`} warn={s.uncategorized_count ? "Not included in income or spending" : undefined} /></Link>
        </div>
      </>}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Spending by category" subtitle="Net of linked refunds">
          {cats.isLoading ? <Spinner /> : <Table>
            <thead><tr><th>Category</th><th className="text-right">Gross</th><th className="text-right">Refunds</th><th className="text-right">Net</th><th className="text-right">Txns</th></tr></thead>
            <tbody>{cats.data?.map((c) => (
              <tr key={c.category_id ?? "u"}><td><Link className="text-primary hover:underline" to={link(c.category_id ? { category_id: c.category_id } : { uncategorized: true })}>{c.category}</Link>
                {c.parent && <span className="text-xs text-subtle"> · {c.parent}</span>}</td>
                <td className="text-right"><Money minor={c.gross_minor} /></td><td className="text-right"><Money minor={c.refunds_minor} /></td>
                <td className="text-right font-medium"><Money minor={c.net_minor} /></td><td className="num text-right">{c.count}</td></tr>))}
              {!cats.data?.length && <tr><td colSpan={5} className="text-subtle">No categorized spending in this period.</td></tr>}
            </tbody>
          </Table>}
        </Card>
        <Card title="Income by source">
          <Table>
            <thead><tr><th>Category</th><th className="text-right">Amount</th><th className="text-right">Txns</th></tr></thead>
            <tbody>{income.data?.map((c) => (
              <tr key={c.category_id ?? "u"}><td><Link className="text-primary hover:underline" to={link({ category_id: c.category_id })}>{c.category}</Link></td>
                <td className="text-right"><Money minor={c.gross_minor} /></td><td className="num text-right">{c.count}</td></tr>))}
              {!income.data?.length && <tr><td colSpan={3} className="text-subtle">No income in this period.</td></tr>}
            </tbody>
          </Table>
        </Card>

        <Card title="Month over month" subtitle="Last 12 months">
          <Legend items={[{ label: "Income", color: SERIES[0] }, { label: "Net spending", color: SERIES[1] }]} />
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={monthly.data ?? []} barGap={2}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
              <YAxis tickFormatter={compactInr} {...axisProps} width={60} />
              <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgb(var(--muted))" }} />
              <Bar dataKey="income" name="Income" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar dataKey="net_spending" name="Net spending" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
          <ChartTable caption="Month over month" columns={["Month", "Income", "Net spending", "Net savings", "Investments"]}
            rows={(monthly.data ?? []).map((m) => [fmtMonth(m.month), inr(m.income), inr(m.net_spending), inr(m.net_savings), inr(m.investment_contributions)])} />
        </Card>

        <Card title="Top merchants">
          <Table>
            <thead><tr><th>Merchant</th><th className="text-right">Net spent</th><th className="text-right">Txns</th></tr></thead>
            <tbody>{merchants.data?.slice(0, 15).map((m) => (
              <tr key={m.merchant}><td><Link className="text-primary hover:underline" to={link({ q: m.merchant === "(unknown merchant)" ? undefined : m.merchant })}>{m.merchant}</Link></td>
                <td className="text-right"><Money minor={m.net_minor} /></td><td className="num text-right">{m.count}</td></tr>))}
            </tbody>
          </Table>
        </Card>

        <Card title="Largest expenses">
          <Table><tbody>{largest.data?.slice(0, 10).map((t) => (
            <tr key={t.transaction_id}><td className="whitespace-nowrap">{fmtDate(t.date)}</td><td className="max-w-xs truncate">{t.description}</td><td className="text-right"><Money minor={t.amount_minor} /></td></tr>))}
            {!largest.data?.length && <tr><td className="text-subtle">None.</td></tr>}</tbody></Table>
        </Card>

        <Card title="Unusual spending candidates" subtitle="Far above the merchant/category's typical amount over the past year">
          {!unusual.data?.length ? <p className="text-sm text-subtle">Nothing unusual detected.</p> : <Table><tbody>{unusual.data.map((t) => (
            <tr key={t.transaction_id}><td>{fmtDate(t.date)}</td><td className="max-w-xs truncate">{t.description}</td><td className="text-right"><Money minor={t.amount_minor} /></td><td className="text-xs text-subtle">{t.reason}</td></tr>))}</tbody></Table>}
        </Card>
      </div>

      <Card title="Recurring payment candidates" className="mt-4" subtitle="Detected from merchant, amount and interval patterns. Confirming creates a definition only — no future transactions are added.">
        {!recurring.data?.length ? <p className="text-sm text-subtle">No recurring patterns detected yet (needs at least 3 occurrences).</p> : (
          <Table>
            <thead><tr><th>Name</th><th>Cadence</th><th className="text-right">Typical amount</th><th>Typical day</th><th>Seen</th><th>Last</th><th /></tr></thead>
            <tbody>{recurring.data.map((c) => (
              <tr key={c.account_id + c.match_key}><td>{c.name}</td><td>{c.cadence}</td><td className="text-right"><Money minor={c.typical_amount_minor} /></td>
                <td>{c.typical_day}</td><td>{c.occurrences}×</td><td>{fmtDate(c.last_date)}</td>
                <td>{confirmedKeys.has(c.match_key) ? <span className="text-xs text-positive">Confirmed</span> : <Button size="sm" onClick={() => confirm.mutate(c)}>Confirm</Button>}</td></tr>))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
