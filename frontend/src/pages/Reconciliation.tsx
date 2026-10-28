import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Link2, Undo2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, Money, PageHeader, Select, Spinner, Status, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { REL_LABELS, fmtDate, inr, minorToInput, parseRupees } from "@/lib/format";
import { useMut } from "@/lib/hooks";
import type { Paged, Relationship, Statement, Txn } from "@/lib/types";

const TABS = [["suggested", "Suggestions"], ["approved", "Approved"], ["rejected", "Rejected"], ["unmatched", "Unmatched"], ["statements", "Statements"]] as const;

export default function Reconciliation() {
  const [tab, setTab] = useState<string>("suggested");
  const run = useMut(() => api.post<{ created: number }>("/reconciliation/suggest"));
  return (
    <>
      <PageHeader title="Reconciliation" description="Suggested matches never affect reports until you approve them. Approved matches can be undone."
        actions={<Button loading={run.isPending} onClick={() => run.mutate(undefined)}>Find new matches</Button>} />
      {run.data && <p className="mb-3 text-sm text-subtle">{run.data.created} new suggestion(s).</p>}
      <div className="mb-4 flex flex-wrap gap-1" role="tablist">
        {TABS.map(([k, l]) => <Button key={k} role="tab" aria-selected={tab === k} variant={tab === k ? "primary" : "secondary"} size="sm" onClick={() => setTab(k)}>{l}</Button>)}
      </div>
      {tab === "statements" ? <Statements /> : tab === "unmatched" ? <Unmatched /> : <RelList status={tab} />}
    </>
  );
}

function TxnSide({ t, label }: { t: Txn | null; label: string }) {
  if (!t) return null;
  return (
    <div className="min-w-0 flex-1 rounded-md border border-border p-3">
      <p className="text-xs font-semibold text-subtle">{label} · {t.account_name}</p>
      <p className="mt-1 text-base font-semibold"><Money minor={t.amount_minor} colored /></p>
      <p className="text-xs text-subtle">{fmtDate(t.transaction_date)}{t.reference ? ` · Ref ${t.reference}` : ""}</p>
      <p className="mt-1 break-words text-sm">{t.normalized_description}</p>
      <p className="mt-1 text-xs text-subtle">Category: {t.category_name ?? "uncategorized"}</p>
    </div>
  );
}

function RelList({ status }: { status: string }) {
  const q = useQuery({ queryKey: ["relationships", status], queryFn: () => api.get<Paged<Relationship> & { matching_window_days: number }>("/reconciliation/relationships", { status, page_size: 100 }) });
  const [partial, setPartial] = useState<Relationship | null>(null);
  const approve = useMut((r: { id: number; amt?: number }) => api.post(`/reconciliation/relationships/${r.id}/approve`, r.amt != null ? { matched_amount_minor: r.amt } : {}));
  const reject = useMut((id: number) => api.post(`/reconciliation/relationships/${id}/reject`));
  const undo = useMut((id: number) => api.post(`/reconciliation/relationships/${id}/undo`));
  const busy = approve.isPending || reject.isPending || undo.isPending || q.isFetching;
  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const items = q.data!.items;
  if (!items.length) return <Empty title={status === "suggested" ? "No suggestions to review" : `No ${status} matches`}>
    {status === "suggested" && <>Matches are suggested after imports using amounts, dates within {q.data!.matching_window_days} days, references and descriptions. The window can be changed in Settings.</>}</Empty>;
  return (
    <div className="space-y-3">
      <ErrorBox error={approve.error || reject.error || undo.error} />
      {items.map((r) => {
        const reasons = r.matching_reason?.reasons ?? [];
        const diff = r.matching_reason?.amount_difference_minor;
        return (
          <Card key={r.id} title={<span className="flex items-center gap-2">{REL_LABELS[r.relationship_type]} <Status status={r.review_status} />
            {r.score != null && <Badge tone="neutral">score {Math.round(r.score * 100)}</Badge>}</span>}
            actions={<>
              {(r.review_status === "suggested" || r.review_status === "undone") && <>
                <Button size="sm" variant="primary" disabled={busy} loading={approve.isPending && approve.variables?.id === r.id} onClick={() => approve.mutate({ id: r.id })}><Check className="h-4 w-4" />Approve</Button>
                <Button size="sm" disabled={busy} onClick={() => setPartial(r)}>Approve partial…</Button>
                {r.review_status === "suggested" && <Button size="sm" disabled={busy} onClick={() => reject.mutate(r.id)}><X className="h-4 w-4" />Reject</Button>}
              </>}
              {r.review_status === "approved" && <Button size="sm" disabled={busy} onClick={() => undo.mutate(r.id)}><Undo2 className="h-4 w-4" />Undo</Button>}
            </>}>
            <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
              <TxnSide t={r.source} label={r.relationship_type === "refund" ? "Purchase" : "Money out"} />
              <ArrowRight className="mx-auto h-5 w-5 shrink-0 rotate-90 text-subtle md:rotate-0" aria-hidden />
              <TxnSide t={r.related} label={r.relationship_type === "refund" ? "Refund" : "Money in"} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
              {reasons.map((x) => <Badge key={x} tone="info">{x}</Badge>)}
              {r.matched_amount_minor != null && <Badge>Matched {inr(r.matched_amount_minor)}</Badge>}
              {diff ? <Badge tone="warn">Unmatched difference {inr(Math.abs(diff))}</Badge> : null}
            </div>
            {r.review_status === "suggested" && <p className="mt-2 text-xs text-subtle">Date and amount similarity alone do not prove a match — check the descriptions.</p>}
          </Card>
        );
      })}
      {partial && <PartialModal rel={partial} onClose={() => setPartial(null)} onApprove={(amt) => approve.mutate({ id: partial.id, amt }, { onSuccess: () => setPartial(null) })} />}
    </div>
  );
}

function PartialModal({ rel, onClose, onApprove }: { rel: Relationship; onClose: () => void; onApprove: (amt: number) => void }) {
  const [v, setV] = useState(minorToInput(rel.matched_amount_minor));
  const amt = parseRupees(v);
  return (
    <Modal open onClose={onClose} title="Approve a partial match" footer={<><Button onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!amt || amt <= 0} onClick={() => amt && onApprove(amt)}>Approve</Button></>}>
      <p className="mb-2 text-sm">Only the matched amount is treated as {REL_LABELS[rel.relationship_type].toLowerCase()}; any remainder keeps its own category.</p>
      <Field label="Matched amount (₹)"><Input inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} /></Field>
    </Modal>
  );
}

function Unmatched() {
  const q = useQuery({ queryKey: ["unmatched"], queryFn: () => api.get<Paged<Txn>>("/reconciliation/unmatched", { page_size: 100 }) });
  const [link, setLink] = useState<Txn | null>(null);
  if (q.isLoading) return <Spinner />;
  return (
    <Card title="Unmatched transfers & payments" subtitle="NEFT/IMPS/UPI/card payments with no approved counterpart. Link them, or categorize them if the other side is not tracked.">
      {!q.data?.items.length ? <p className="text-sm text-subtle">Nothing unmatched.</p> : (
        <Table>
          <thead><tr><th>Date</th><th>Account</th><th>Description</th><th className="text-right">Amount</th><th>Category</th><th /></tr></thead>
          <tbody>{q.data.items.map((t) => (
            <tr key={t.id}><td>{fmtDate(t.transaction_date)}</td><td className="text-xs">{t.account_name}</td><td className="max-w-md truncate">{t.normalized_description}</td>
              <td className="text-right"><Money minor={t.amount_minor} colored /></td><td className="text-xs">{t.category_name ?? "—"}</td>
              <td><Button size="sm" onClick={() => setLink(t)}><Link2 className="h-4 w-4" />Link…</Button></td></tr>))}
          </tbody>
        </Table>
      )}
      {link && <LinkModal txn={link} onClose={() => setLink(null)} />}
    </Card>
  );
}

function LinkModal({ txn, onClose }: { txn: Txn; onClose: () => void }) {
  const cands = useQuery({ queryKey: ["candidates", txn.id], queryFn: () => api.get<Txn[]>(`/reconciliation/candidates/${txn.id}`) });
  const [other, setOther] = useState<number | null>(null);
  const [type, setType] = useState("transfer");
  const [amount, setAmount] = useState(minorToInput(Math.abs(txn.amount_minor)));
  const create = useMut(() => {
    const o = cands.data!.find((c) => c.id === other)!;
    const [src, rel] = type === "refund" ? (txn.amount_minor < 0 ? [txn, o] : [o, txn]) : (txn.amount_minor < 0 ? [txn, o] : [o, txn]);
    return api.post("/reconciliation/relationships", { source_transaction_id: src.id, related_transaction_id: rel.id, relationship_type: type,
      matched_amount_minor: parseRupees(amount) ?? undefined });
  }, onClose);
  return (
    <Modal open wide onClose={onClose} title="Link transaction" footer={<><Button onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!other} loading={create.isPending} onClick={() => create.mutate(undefined)}>Create approved link</Button></>}>
      <p className="mb-2 text-sm">{fmtDate(txn.transaction_date)} · {txn.account_name} · <Money minor={txn.amount_minor} /> · {txn.normalized_description}</p>
      <div className="mb-3 grid gap-2 sm:grid-cols-2">
        <Field label="Relationship"><Select value={type} onChange={(e) => setType(e.target.value)}>
          {Object.entries(REL_LABELS).filter(([k]) => k !== "duplicate").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
        <Field label="Matched amount (₹)"><Input value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      </div>
      {cands.isLoading ? <Spinner /> : !cands.data?.length ? <p className="text-sm text-subtle">No candidates with a similar amount nearby.</p> : (
        <Table>
          <thead><tr><th /><th>Date</th><th>Account</th><th>Description</th><th className="text-right">Amount</th></tr></thead>
          <tbody>{cands.data.map((c) => (
            <tr key={c.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setOther(c.id)}>
              <td><input type="radio" name="cand" checked={other === c.id} onChange={() => setOther(c.id)} aria-label={`Choose ${c.id}`} /></td>
              <td>{fmtDate(c.transaction_date)}</td><td className="text-xs">{c.account_name}</td><td className="max-w-sm truncate">{c.normalized_description}</td>
              <td className="text-right"><Money minor={c.amount_minor} colored /></td></tr>))}
          </tbody>
        </Table>
      )}
      <ErrorBox error={create.error} />
    </Modal>
  );
}

function Statements() {
  const q = useQuery({ queryKey: ["statements"], queryFn: () => api.get<Statement[]>("/reconciliation/statements") });
  const recheck = useMut((id: number) => api.post(`/reconciliation/statements/${id}/recheck`));
  if (q.isLoading) return <Spinner />;
  if (!q.data?.length) return <Empty title="No statements imported yet" />;
  return (
    <Card title="Statement reconciliation" subtitle="Reported opening + signed movements = reported closing. Differences are shown, never forced away.">
      <Table>
        <thead><tr><th>Account</th><th>Period</th><th className="text-right">Opening</th><th className="text-right">Reported closing</th><th className="text-right">Calculated closing</th><th className="text-right">Difference</th><th>Status</th><th /></tr></thead>
        <tbody>{q.data.map((s) => (
          <tr key={s.id}>
            <td>{s.account_name}</td><td className="whitespace-nowrap">{fmtDate(s.start_date)} – {fmtDate(s.end_date)}</td>
            <td className="text-right"><Money minor={s.reported_opening_minor} /></td><td className="text-right"><Money minor={s.reported_closing_minor} /></td>
            <td className="text-right"><Money minor={s.calculated_closing_minor} /></td>
            <td className="text-right">{s.discrepancy_minor ? <Money minor={s.discrepancy_minor} className="font-semibold text-negative" /> : "—"}</td>
            <td><Status status={s.reconciliation_status} /></td>
            <td className="whitespace-nowrap"><Button size="sm" variant="ghost" onClick={() => recheck.mutate(s.id)}>Recheck</Button>
              <Link className="ml-1 text-xs text-primary hover:underline" to={`/import/${s.import_batch_id}`}>Import</Link></td>
          </tr>))}
        </tbody>
      </Table>
      <p className="mt-2 text-xs text-subtle">Common causes of differences: a row the parser missed (see the import's skipped lines), a sign read the wrong way, or an opening balance that belongs to a different date.</p>
    </Card>
  );
}
