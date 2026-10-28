import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CategorySelect } from "@/components/CategorySelect";
import { TransactionDetail } from "@/components/TransactionDetail";
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, Money, PageHeader, Pagination, Select, Spinner, Table } from "@/components/ui";
import { api, download } from "@/lib/api";
import { CLASS_LABELS, fmtDate, parseRupees, todayIso } from "@/lib/format";
import { useAccounts, useMut } from "@/lib/hooks";
import type { Paged, Txn } from "@/lib/types";

const FILTER_KEYS = ["q", "account_id", "category_id", "start", "end", "direction", "reporting_class", "uncategorized", "reconciliation_status", "import_batch_id", "ids"];

export default function Transactions() {
  const [sp, setSp] = useSearchParams();
  const accounts = useAccounts();
  const page = Number(sp.get("page") ?? 1);
  const sort = sp.get("sort") ?? "date";
  const order = sp.get("order") ?? "desc";
  const params = useMemo(() => {
    const p: Record<string, string | string[]> = { page: String(page), page_size: "50", sort, order };
    for (const k of FILTER_KEYS) {
      const all = sp.getAll(k);
      if (all.length) p[k] = all.length > 1 ? all : all[0];
    }
    return p;
  }, [sp, page, sort, order]);
  const q = useQuery({ queryKey: ["transactions", params], queryFn: () => api.get<Paged<Txn>>("/transactions", params), placeholderData: keepPreviousData });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<number | null>(null);
  const [bulkCat, setBulkCat] = useState<number | null>(null);
  const [manual, setManual] = useState(false);

  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    if (v === null || v === "") n.delete(k); else n.set(k, v);
    if (k !== "page") n.delete("page");
    setSp(n);
  };
  const toggleSort = (col: string) => {
    const n = new URLSearchParams(sp);
    n.set("sort", col);
    n.set("order", sort === col && order === "desc" ? "asc" : "desc");
    setSp(n);
  };
  const bulk = useMut(() => api.post("/transactions/bulk-categorize", { transaction_ids: [...selected], category_id: bulkCat }), () => setSelected(new Set()));
  const items = q.data?.items ?? [];
  const allSel = items.length > 0 && items.every((t) => selected.has(t.id));
  const SortHead = ({ col, children, right }: { col: string; children: React.ReactNode; right?: boolean }) => (
    <th className={right ? "text-right" : ""} aria-sort={sort === col ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button className="focus-ring inline-flex items-center gap-1 rounded" onClick={() => toggleSort(col)}>
        {children}{sort === col && (order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );
  const exportParams = Object.fromEntries(Object.entries(params).filter(([k]) => ["q", "account_id", "category_id", "start", "end"].includes(k)));

  return (
    <>
      <PageHeader title="Transactions" description="The ledger is the source of truth. Original statement values are preserved; edits are audited."
        actions={<>
          <Button onClick={() => setManual(true)}><Plus className="h-4 w-4" />Manual entry</Button>
          <Button onClick={() => download("/transactions/export", { ...exportParams, fmt: "csv" })}><Download className="h-4 w-4" />CSV</Button>
          <Button onClick={() => download("/transactions/export", { ...exportParams, fmt: "xlsx" })}><Download className="h-4 w-4" />Excel</Button>
        </>} />

      <Card>
        <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-8">
          <Input className="md:col-span-2" placeholder="Search description, merchant, reference, notes" aria-label="Search" defaultValue={sp.get("q") ?? ""}
            onKeyDown={(e) => e.key === "Enter" && setParam("q", (e.target as HTMLInputElement).value)} onBlur={(e) => setParam("q", e.target.value)} />
          <Select aria-label="Account" value={sp.get("account_id") ?? ""} onChange={(e) => setParam("account_id", e.target.value)}>
            <option value="">All accounts</option>
            {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
          <CategorySelect value={sp.get("category_id") ? Number(sp.get("category_id")) : null} noneLabel="All categories" onChange={(v) => setParam("category_id", v ? String(v) : null)} />
          <Input type="date" aria-label="From date" value={sp.get("start") ?? ""} onChange={(e) => setParam("start", e.target.value)} />
          <Input type="date" aria-label="To date" value={sp.get("end") ?? ""} onChange={(e) => setParam("end", e.target.value)} />
          <Select aria-label="Reporting class" value={sp.get("reporting_class") ?? ""} onChange={(e) => setParam("reporting_class", e.target.value)}>
            <option value="">All classes</option>
            {Object.entries(CLASS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Select aria-label="Direction" value={sp.get("direction") ?? ""} onChange={(e) => setParam("direction", e.target.value)}>
            <option value="">In & out</option><option value="debit">Money out</option><option value="credit">Money in</option>
          </Select>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={sp.get("uncategorized") === "true"} onChange={(e) => setParam("uncategorized", e.target.checked ? "true" : null)} /> Uncategorized only</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={sp.get("reconciliation_status") === "unreconciled"} onChange={(e) => setParam("reconciliation_status", e.target.checked ? "unreconciled" : null)} /> Unmatched only</label>
          {[...sp.keys()].some((k) => FILTER_KEYS.includes(k)) && <Button size="sm" variant="ghost" onClick={() => setSp(new URLSearchParams())}>Clear filters</Button>}
        </div>
      </Card>

      {selected.size > 0 && (
        <div className="sticky top-0 z-10 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
          <b>{selected.size} selected</b>
          <div className="w-64"><CategorySelect value={bulkCat} onChange={setBulkCat} /></div>
          <Button size="sm" variant="primary" loading={bulk.isPending} onClick={() => bulk.mutate(undefined)}>Apply category</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
          <ErrorBox error={bulk.error} />
        </div>
      )}

      <div className="mt-3 rounded-lg border border-border bg-surface">
        {q.isLoading ? <Spinner /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} /></div> : (
          <Table>
            <thead><tr>
              <th className="w-8"><input type="checkbox" aria-label="Select all on page" checked={allSel}
                onChange={() => setSelected(allSel ? new Set() : new Set(items.map((t) => t.id)))} /></th>
              <SortHead col="date">Date</SortHead><th>Account</th><SortHead col="description">Description</SortHead>
              <SortHead col="merchant">Merchant</SortHead><th>Category</th><th>Class</th><SortHead col="amount" right>Amount</SortHead>
            </tr></thead>
            <tbody>
              {items.length === 0 && <tr><td colSpan={8} className="py-8 text-center text-subtle">No transactions match these filters.</td></tr>}
              {items.map((t) => (
                <tr key={t.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setDetail(t.id)}>
                  <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select transaction ${t.id}`} checked={selected.has(t.id)}
                    onChange={() => { const n = new Set(selected); n.has(t.id) ? n.delete(t.id) : n.add(t.id); setSelected(n); }} /></td>
                  <td className="whitespace-nowrap">{fmtDate(t.transaction_date)}</td>
                  <td className="whitespace-nowrap text-xs">{t.account_name}</td>
                  <td className="max-w-md"><button className="focus-ring line-clamp-2 rounded text-left" onClick={(e) => { e.stopPropagation(); setDetail(t.id); }}>{t.normalized_description}</button>
                    {t.notes && <div className="truncate text-xs text-subtle">{t.notes}</div>}</td>
                  <td className="text-xs">{t.merchant}</td>
                  <td className="text-xs">{t.category_name ?? <Badge tone="warn">Uncategorized</Badge>}{t.category_source === "rule" && <span className="ml-1 text-subtle" title="Set by a rule">·r</span>}</td>
                  <td>{t.reporting_parts?.map((p, i) => <Badge key={i} tone={p.class === "uncategorized" ? "warn" : "neutral"}>{CLASS_LABELS[p.class] ?? p.class}</Badge>)}</td>
                  <td className="text-right font-medium"><Money minor={t.amount_minor} colored /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="px-3 pb-3">{q.data && <Pagination page={page} pageSize={50} total={q.data.total} onPage={(p) => setParam("page", String(p))} />}</div>
      </div>

      {detail !== null && <TransactionDetail id={detail} onClose={() => setDetail(null)} />}
      {manual && <ManualEntry onClose={() => setManual(false)} />}
    </>
  );
}

function ManualEntry({ onClose }: { onClose: () => void }) {
  const accounts = useAccounts();
  const [f, setF] = useState({ account_id: "", date: todayIso(), description: "", amount: "", out: true, category_id: null as number | null });
  const [err, setErr] = useState<string | null>(null);
  const save = useMut(() => {
    const v = parseRupees(f.amount);
    if (!f.account_id || !v || v < 0) throw new Error("Choose an account and enter a positive amount");
    return api.post("/transactions", { account_id: Number(f.account_id), transaction_date: f.date, description: f.description,
      amount_minor: f.out ? -v : v, category_id: f.category_id });
  }, onClose);
  return (
    <Modal open onClose={onClose} title="Manual transaction" footer={<><Button onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined, { onError: (e) => setErr(e.message) })}>Save</Button></>}>
      <p className="mb-3 text-xs text-subtle">For movements without a statement (e.g. cash). Marked as manual and never part of statement reconciliation.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Account"><Select value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}>
          <option value="">Choose…</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Field label="Description"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field></div>
        <Field label="Amount (₹)"><Input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Direction"><Select value={f.out ? "out" : "in"} onChange={(e) => setF({ ...f, out: e.target.value === "out" })}>
          <option value="out">Money out / owed more</option><option value="in">Money in / owed less</option></Select></Field>
        <div className="sm:col-span-2"><Field label="Category"><CategorySelect value={f.category_id} onChange={(v) => setF({ ...f, category_id: v })} /></Field></div>
      </div>
      <div className="mt-3"><ErrorBox error={err} /></div>
    </Modal>
  );
}
