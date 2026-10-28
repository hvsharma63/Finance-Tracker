import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { CategorySelect } from "@/components/CategorySelect";
import { Button, Card, Empty, ErrorBox, Field, Input, Money, PageHeader, Spinner, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { inr, parseRupees, todayIso } from "@/lib/format";
import { useCategories, useMut } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function Budgets() {
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const status = useQuery({ queryKey: ["budget-status", month], queryFn: () => api.get<any>("/budgets/status", { month: `${month}-01` }) });
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: () => api.get<any[]>("/budgets") });
  const recurring = useQuery({ queryKey: ["recurring"], queryFn: () => api.get<any[]>("/recurring") });
  const cats = useCategories();
  const [cat, setCat] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [onlyThisMonth, setOnlyThisMonth] = useState(false);
  const create = useMut(() => {
    const v = parseRupees(amount);
    if (!cat || !v || v <= 0) throw new Error("Choose an expense category and a positive amount");
    return api.post("/budgets", { category_id: cat, amount_minor: v, month: onlyThisMonth ? `${month}-01` : null });
  }, () => setAmount(""));
  const remove = useMut((id: number) => api.del(`/budgets/${id}`));
  const removeRec = useMut((id: number) => api.del(`/recurring/${id}`));
  const catName = (id: number) => cats.data?.find((c) => c.id === id)?.name ?? id;

  return (
    <>
      <PageHeader title="Budgets" description="Monthly category budgets compared with actual net spending (expenses minus linked refunds)."
        actions={<Input type="month" aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} className="w-44" />} />
      <Card title={`Budget status · ${month}`} subtitle={status.data?.note}>
        {status.isLoading ? <Spinner /> : !status.data?.items.length ? <Empty title="No budgets yet">Add a budget below. A budget on a parent category (e.g. Lifestyle spending) includes its subcategories.</Empty> : (
          <div className="space-y-3">
            {status.data.items.map((b: any) => {
              const pct = Math.min(100, b.percent_used);
              const over = b.percent_used > 100;
              return (
                <div key={b.budget_id}>
                  <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <span className="font-medium">{b.category}{b.is_default ? "" : " (this month only)"}</span>
                    <span className="num">{inr(b.spent_minor)} of {inr(b.budget_minor)} · <span className={over ? "font-semibold text-negative" : ""}>{b.percent_used}%{over && " — over budget"}</span></span>
                  </div>
                  <div className="mt-1 h-2.5 rounded-full bg-muted" role="progressbar" aria-valuenow={b.percent_used} aria-valuemin={0} aria-valuemax={100} aria-label={`${b.category} budget used`}>
                    <div className={clsx("h-2.5 rounded-full", over ? "bg-negative" : "bg-primary")} style={{ width: `${pct}%` }} />
                  </div>
                  <p className="mt-0.5 text-xs text-subtle">Remaining {inr(b.remaining_minor)}{b.projected_minor != null && ` · projected ${inr(b.projected_minor)} by month end`}</p>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Add budget">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Expense category"><CategorySelect value={cat} onChange={setCat} noneLabel="Choose…" /></Field>
            <Field label="Monthly amount (₹)"><Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          </div>
          <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyThisMonth} onChange={(e) => setOnlyThisMonth(e.target.checked)} />Only for {month} (otherwise every month)</label>
          <ErrorBox error={create.error} />
          <Button className="mt-3" variant="primary" loading={create.isPending} onClick={() => create.mutate(undefined)}>Add budget</Button>
          {budgets.data && budgets.data.length > 0 && (
            <Table className="mt-4"><thead><tr><th>Category</th><th>Month</th><th className="text-right">Amount</th><th /></tr></thead>
              <tbody>{budgets.data.map((b) => <tr key={b.id}><td>{catName(b.category_id)}</td><td>{b.month ?? "Every month"}</td><td className="text-right"><Money minor={b.amount_minor} /></td>
                <td><Button size="sm" variant="ghost" aria-label="Delete budget" onClick={() => remove.mutate(b.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>)}</tbody></Table>
          )}
        </Card>
        <Card title="Confirmed recurring payments" subtitle="Confirm candidates on the Spending & Income page. These are definitions only.">
          {!recurring.data?.length ? <p className="text-sm text-subtle">None confirmed.</p> : (
            <Table><thead><tr><th>Name</th><th>Cadence</th><th className="text-right">Expected</th><th>Day</th><th /></tr></thead>
              <tbody>{recurring.data.map((r) => <tr key={r.id}><td>{r.name}</td><td>{r.cadence}</td><td className="text-right"><Money minor={r.expected_amount_minor} /></td><td>{r.typical_day ?? ""}</td>
                <td><Button size="sm" variant="ghost" aria-label="Remove" onClick={() => removeRec.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>)}</tbody></Table>
          )}
        </Card>
      </div>
    </>
  );
}
