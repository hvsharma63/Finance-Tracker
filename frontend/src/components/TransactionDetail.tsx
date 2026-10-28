import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { CLASS_LABELS, REL_LABELS, fmtDate, fmtDateTime, inr } from "@/lib/format";
import { useMut } from "@/lib/hooks";
import type { Relationship, Txn } from "@/lib/types";
import { CategorySelect } from "./CategorySelect";
import { Badge, Button, ErrorBox, Field, Input, Modal, Money, Notice, Spinner, Status } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Detail = Txn & { source_data: any; relationships: Relationship[]; history: { at: string; action: string; details: any }[] };

export function TransactionDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["transaction", id], queryFn: () => api.get<Detail>(`/transactions/${id}`) });
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [ruleSuggestion, setRuleSuggestion] = useState<any>(null);
  const save = useMut((body: Record<string, unknown>) => api.patch<any>(`/transactions/${id}`, body), (r) => {
    setEdits({});
    if (r.rule_suggestion) setRuleSuggestion(r.rule_suggestion);
  });
  const createRule = useMut(() => api.post("/rules", { ...ruleSuggestion, apply_now: true }), () => setRuleSuggestion(null));
  const t = q.data;

  return (
    <Modal open onClose={onClose} title={`Transaction #${id}`} wide footer={<>
      <Button onClick={onClose}>Close</Button>
      <Button variant="primary" disabled={!Object.keys(edits).length} loading={save.isPending} onClick={() => save.mutate(edits)}>Save changes</Button>
    </>}>
      {!t ? <Spinner /> : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-lg font-semibold"><Money minor={t.amount_minor} colored /></p>
              <p className="text-subtle">{fmtDate(t.transaction_date)} · {t.account_name} {t.posting_date && t.posting_date !== t.transaction_date ? `· value date ${fmtDate(t.posting_date)}` : ""}</p>
            </div>
            <div className="flex flex-wrap gap-1">
              {t.reporting_parts?.map((p, i) => <Badge key={i} tone="info">{CLASS_LABELS[p.class]}: {inr(p.amount_minor)}</Badge>)}
              <Status status={t.reconciliation_status === "reconciled" ? "reconciled" : "unverifiable"} />
              {t.is_manual && <Badge>Manual</Badge>}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Category"><CategorySelect value={(edits.category_id as number | null | undefined) ?? t.category_id} onChange={(v) => setEdits({ ...edits, category_id: v })} /></Field>
            <Field label="Merchant"><Input defaultValue={t.merchant ?? ""} onChange={(e) => setEdits({ ...edits, merchant: e.target.value || null })} /></Field>
            <Field label="Description (normalized)"><Input defaultValue={t.normalized_description} onChange={(e) => setEdits({ ...edits, normalized_description: e.target.value })} /></Field>
            <Field label="Tags" hint="Comma separated"><Input defaultValue={t.tags.join(", ")} onChange={(e) => setEdits({ ...edits, tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
            <div className="md:col-span-2"><Field label="Notes"><Input defaultValue={t.notes ?? ""} onChange={(e) => setEdits({ ...edits, notes: e.target.value || null })} /></Field></div>
          </div>
          <ErrorBox error={save.error} />

          {ruleSuggestion && (
            <Notice tone="info">
              <p>Create a rule so similar transactions are categorized automatically?</p>
              <p className="mt-1 text-xs text-subtle">{ruleSuggestion.name}: {ruleSuggestion.conditions.conditions.map((c: any) => `${c.field} ${c.op} "${c.value}"`).join(" AND ")}</p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="primary" loading={createRule.isPending} onClick={() => createRule.mutate(undefined)}>Create rule</Button>
                <Button size="sm" onClick={() => setRuleSuggestion(null)}>No thanks</Button>
              </div>
              <ErrorBox error={createRule.error} />
            </Notice>
          )}

          <div className="rounded-md border border-border p-3">
            <p className="mb-2 text-xs font-semibold text-subtle">ORIGINAL STATEMENT VALUES (never modified)</p>
            <dl className="grid gap-x-4 gap-y-1 text-xs md:grid-cols-[10rem_1fr]">
              <dt className="text-subtle">Description</dt><dd className="break-all">{t.original_description}</dd>
              <dt className="text-subtle">Amount</dt><dd>{inr(t.original_amount_minor)}</dd>
              <dt className="text-subtle">Reference</dt><dd>{t.reference ?? "—"}</dd>
              <dt className="text-subtle">Type</dt><dd>{t.transaction_type ?? "—"}</dd>
              <dt className="text-subtle">Balance after</dt><dd>{inr(t.balance_after_minor)}</dd>
              <dt className="text-subtle">Source</dt><dd>{t.source_row_reference ?? "manual"} {t.parser_name && `· ${t.parser_name}`} {t.import_batch_id && `· import #${t.import_batch_id}`}</dd>
            </dl>
          </div>

          {t.relationships.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold text-subtle">RELATIONSHIPS</p>
              <ul className="space-y-1">{t.relationships.map((r) => {
                const other = r.source_transaction_id === t.id ? r.related : r.source;
                return <li key={r.id} className="flex flex-wrap items-center gap-2 text-xs"><Status status={r.review_status} />{REL_LABELS[r.relationship_type]}
                  <span className="text-subtle">with #{other?.id} {other?.account_name} {fmtDate(other?.transaction_date)} {inr(other?.amount_minor)}</span>
                  {r.matched_amount_minor != null && <span>matched {inr(r.matched_amount_minor)}</span>}</li>;
              })}</ul>
            </div>
          )}

          {t.history.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold text-subtle">HISTORY</p>
              <ul className="space-y-1 text-xs">{t.history.map((h, i) => (
                <li key={i}><span className="text-subtle">{fmtDateTime(h.at)}</span> {h.action}: {JSON.stringify(h.details?.after ?? h.details)}</li>
              ))}</ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
