import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AXIS, ChartTable, GRID, Legend, MoneyTooltip, SERIES, axisProps, compactInr } from "@/components/charts";
import { Button, Card, Empty, ErrorBox, Money, Notice, PageHeader, Spinner, Stat, Status } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { ACCOUNT_TYPE_LABELS, fmtDate, fmtMonth, inr, monthStartIso, todayIso } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Dash = any;

export default function Dashboard() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/reports/dashboard") });
  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;
  const c = d.cards;
  const cm = d.current_month;

  if (!d.has_data && d.balances.length === 0) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <Empty title="No financial data yet" action={<div className="flex gap-2">
          <Button variant="primary" onClick={() => nav("/accounts")}>Add an account</Button>
          <Button onClick={() => nav("/import")}>Import a statement</Button></div>}>
          Everything here is calculated from statements you import. Start by adding your bank and card accounts, then
          upload a statement (CSV, Excel or PDF).
        </Empty>
      </>
    );
  }

  const monthTxns = (cls: string) => `/transactions${qs({ start: monthStartIso(), end: todayIso(), reporting_class: cls })}`;
  const stale = d.balances.filter((b: any) => b.is_stale);
  const monthly = d.monthly as any[];

  return (
    <>
      <PageHeader title="Dashboard" description={<>
        Figures are derived from imported statements. Latest statement date: <b>{fmtDate(d.latest_statement_date)}</b>.
        Balances are as of each account's coverage date, not live.</>} />

      {(stale.length > 0 || c.unknown_balance_accounts.length > 0 || cm.coverage_warnings.length > 0) && (
        <div className="mb-4 space-y-2">
          {stale.length > 0 && <Notice>Not updated in 45+ days: {stale.map((s: any) => `${s.name} (${s.coverage_end ? "to " + fmtDate(s.coverage_end) : "no statements"})`).join(", ")}.</Notice>}
          {c.unknown_balance_accounts.length > 0 && <Notice>Opening balance unknown — excluded from totals: {c.unknown_balance_accounts.join(", ")}. Set it on the account page.</Notice>}
          {cm.coverage_warnings.map((w: string) => <Notice key={w} tone="info">{w}</Notice>)}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Bank & cash balances" value={inr(c.cash_minor)} />
        <Stat label="Credit card outstanding" value={inr(c.credit_card_outstanding_minor)} />
        <Stat label="Loans & other liabilities" value={inr(c.loans_minor + c.other_liabilities_minor)} />
        <Stat label="Investments (valued)" value={inr(c.investments_valued_minor + c.fixed_deposits_minor)}
          sub={c.fixed_deposits_minor ? `incl. fixed deposits ${inr(c.fixed_deposits_minor)}` : undefined}
          warn={c.investments_unvalued_cost_minor ? `${inr(c.investments_unvalued_cost_minor)} at cost has no valuation` : undefined} />
        <Stat label="Total assets" value={inr(c.total_assets_minor)} />
        <Stat label="Total liabilities" value={inr(c.total_liabilities_minor)} />
        <Stat label="Estimated net worth" value={inr(c.net_worth_minor)}
          warn={c.net_worth_is_estimate ? "Estimate: includes unvalued holdings at cost or unverified balances" : undefined} />
        <Stat label="Uncategorized this month" value={String(cm.uncategorized_count)}
          sub={<Link className="text-primary hover:underline" to="/transactions?uncategorized=true">Review queue →</Link>} />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link to={monthTxns("income")} className="focus-ring rounded-lg"><Stat label="Income this month" value={inr(cm.income)} sub="Excludes transfers, refunds, card repayments" /></Link>
        <Link to={monthTxns("expense")} className="focus-ring rounded-lg"><Stat label="Net spending this month" value={inr(cm.net_spending)}
          sub={`Expenses ${inr(cm.expenses)} − refunds ${inr(cm.refunds)}`} /></Link>
        <Stat label="Net savings this month" value={<span className={cm.net_savings < 0 ? "text-negative" : ""}>{inr(cm.net_savings)}</span>}
          sub={`Investments contributed: ${inr(cm.investment_contributions)}`} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Income vs expenses" subtitle="Monthly, last 12 months · net spending = expenses − refunds">
          <Legend items={[{ label: "Income", color: SERIES[0] }, { label: "Net spending", color: SERIES[1] }]} />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={monthly} barGap={2}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
              <YAxis tickFormatter={compactInr} {...axisProps} width={60} />
              <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgb(var(--muted))" }} />
              <Bar dataKey="income" name="Income" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar dataKey="net_spending" name="Net spending" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
          <ChartTable caption="Monthly income and spending" columns={["Month", "Income", "Net spending", "Net savings"]}
            rows={monthly.map((m) => [fmtMonth(m.month), inr(m.income), inr(m.net_spending), inr(m.net_savings)])} />
        </Card>

        <Card title="Spending by category" subtitle="This month · click a category to see its transactions">
          {d.categories_current_month.length === 0 ? <p className="text-sm text-subtle">No categorized spending this month.</p> : (
            <ul className="space-y-2">
              {d.categories_current_month.map((r: any) => {
                const max = d.categories_current_month[0].net_minor || 1;
                return (
                  <li key={r.category_id ?? "none"}>
                    <Link to={`/transactions${qs({ start: monthStartIso(), end: todayIso(), category_id: r.category_id ?? undefined, uncategorized: r.category_id ? undefined : true })}`}
                      className="focus-ring group block rounded">
                      <div className="flex justify-between text-xs"><span className="group-hover:underline">{r.category}{r.parent ? <span className="text-subtle"> · {r.parent}</span> : null}</span><span className="num">{inr(r.net_minor)}</span></div>
                      <div className="mt-1 h-2 rounded-full bg-muted"><div className="h-2 rounded-full" style={{ width: `${Math.max(2, (r.net_minor / max) * 100)}%`, background: SERIES[0] }} /></div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Net worth over time" subtitle="Month-end · dashed points are estimates">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={d.net_worth_series}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
              <YAxis tickFormatter={compactInr} {...axisProps} width={60} />
              <Tooltip content={<MoneyTooltip />} />
              <Line dataKey="net_worth_minor" name="Net worth" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, fill: "rgb(var(--surface))" }} />
            </LineChart>
          </ResponsiveContainer>
          <ChartTable caption="Net worth" columns={["Month", "Assets", "Liabilities", "Net worth", "Estimate?"]}
            rows={d.net_worth_series.map((m: any) => [fmtMonth(m.month), inr(m.assets_minor), inr(m.liabilities_minor), inr(m.net_worth_minor), m.is_estimate ? "yes" : "no"])} />
        </Card>

        <Card title="Credit card spending vs repayments" subtitle="Monthly, from card statements">
          <Legend items={[{ label: "Card spending", color: SERIES[1] }, { label: "Repayments", color: SERIES[2] }]} />
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={monthly} barGap={2}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
              <YAxis tickFormatter={compactInr} {...axisProps} width={60} />
              <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgb(var(--muted))" }} />
              <Bar dataKey="card_spending" name="Card spending" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar dataKey="card_repayments" name="Repayments" fill={SERIES[2]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <BalanceTrend series={d.balance_series} balances={d.balances.filter((b: any) => d.cash_account_ids.includes(b.account_id))} />

        <Card title="Asset allocation & investment contributions" subtitle="Holdings by type · monthly contributions">
          {d.allocation.length === 0 ? <p className="text-sm text-subtle">No investment holdings recorded.</p> : (
            <ul className="mb-4 space-y-1.5 text-sm">
              {d.allocation.map((a: any) => (
                <li key={a.instrument_type} className="flex justify-between">
                  <span className="capitalize">{a.instrument_type.replace("_", " ")}</span>
                  <span className="num">{inr(a.value_minor)}{a.unknown_count > 0 && <span className="text-xs text-warning"> + {a.unknown_count} unvalued (cost {inr(a.cost_basis_minor)})</span>}</span>
                </li>
              ))}
            </ul>
          )}
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={monthly}>
              <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
              <YAxis tickFormatter={compactInr} {...axisProps} width={60} />
              <Tooltip content={<MoneyTooltip />} cursor={{ fill: "rgb(var(--muted))" }} />
              <Bar dataKey="investment_contributions" name="Contributions" fill={SERIES[6]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
          <p className="mt-1 text-xs text-subtle">Valuation changes appear on the Investments page once dated valuations are imported.</p>
        </Card>
      </div>

      <Card title="Accounts" className="mt-4">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {d.balances.map((b: any) => (
            <Link key={b.account_id} to={`/accounts/${b.account_id}`} className="focus-ring rounded-md border border-border p-3 hover:bg-muted/50">
              <div className="flex items-start justify-between gap-2">
                <div><p className="text-sm font-medium">{b.name}</p><p className="text-xs text-subtle">{ACCOUNT_TYPE_LABELS[b.account_type]} {b.institution ? `· ${b.institution}` : ""}</p></div>
                <Status status={b.reconciliation_status} />
              </div>
              <p className="mt-2 text-lg font-semibold"><Money minor={b.calculated_balance_minor} /></p>
              <p className="text-xs text-subtle">{b.calculated_balance_minor == null ? "Opening balance unknown" : `As of ${fmtDate(b.coverage_end)}`} · {b.balance_status}</p>
            </Link>
          ))}
        </div>
      </Card>
    </>
  );
}

function BalanceTrend({ series, balances }: { series: any[]; balances: any[] }) {
  const shown = balances.slice(0, 8);
  return (
    <Card title="Bank & cash balance trends" subtitle="Month-end calculated balances">
      {shown.length === 0 ? <p className="text-sm text-subtle">No bank accounts.</p> : <>
        {shown.length > 1 && <Legend items={shown.map((b, i) => ({ label: b.name, color: SERIES[i] }))} />}
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={series}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="month" tickFormatter={fmtMonth} {...axisProps} />
            <YAxis tickFormatter={compactInr} {...axisProps} width={60} stroke={AXIS} />
            <Tooltip content={<MoneyTooltip />} />
            {shown.map((b, i) => (
              <Line key={b.account_id} dataKey={String(b.account_id)} name={b.name} stroke={SERIES[i]} strokeWidth={2} dot={false} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
        {balances.length > 8 && <p className="text-xs text-subtle">Showing the first 8 accounts.</p>}
      </>}
    </Card>
  );
}
