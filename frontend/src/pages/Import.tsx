import { useQuery } from "@tanstack/react-query";
import { FileUp, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Badge, Button, Card, Confirm, ErrorBox, Field, Input, Modal, Money, Notice, PageHeader, Select, Spinner, Status, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ACCOUNT_TYPE_LABELS, fmtDate, fmtDateTime, inr, minorToInput, parseRupees } from "@/lib/format";
import { useAccounts, useMut } from "@/lib/hooks";
import type { Batch, ImportRow, Paged } from "@/lib/types";

export default function ImportPage() {
  const { batchId } = useParams();
  return batchId ? <Preview id={Number(batchId)} /> : <UploadAndHistory />;
}

/* ------------------------------------------------------------------ upload */

function UploadForm({ initialAccount, onDone }: { initialAccount?: string; onDone: (b: Batch) => void }) {
  const accounts = useAccounts();
  const parsers = useQuery({ queryKey: ["parsers"], queryFn: () => api.get<any>("/imports/parsers") });
  const [file, setFile] = useState<File | null>(null);
  const [account, setAccount] = useState(initialAccount ?? "");
  const [stype, setStype] = useState("");
  const [password, setPassword] = useState("");
  const [forceOcr, setForceOcr] = useState(false);
  const [parser, setParser] = useState("");
  const upload = useMut(async () => {
    if (!file) throw new Error("Choose a file");
    const fd = new FormData();
    fd.append("file", file);
    if (account) fd.append("account_id", account);
    if (stype) fd.append("statement_type", stype);
    if (password) fd.append("password", password);
    if (parser) fd.append("parser_name", parser);
    if (forceOcr) fd.append("force_ocr", "true");
    return api.post<Batch>("/imports", fd);
  }, onDone);
  const acct = accounts.data?.find((a) => String(a.id) === account);

  return (
    <form onSubmit={(e) => { e.preventDefault(); upload.mutate(undefined); }} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Statement file" hint={`CSV, XLSX, XLS or PDF (digital or scanned), up to ${parsers.data?.max_upload_mb ?? 25} MB. The file is stored privately on this machine.`}>
          <Input type="file" accept=".csv,.txt,.xlsx,.xlsm,.xls,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Account" hint="Leave as 'detect' to match by the last 4 digits printed on the statement.">
          <Select value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">Detect from statement</option>
            {accounts.data?.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name} ({ACCOUNT_TYPE_LABELS[a.account_type]})</option>)}
          </Select>
        </Field>
        <Field label="Statement type">
          <Select value={stype} onChange={(e) => setStype(e.target.value)}>
            <option value="">Auto-detect{acct?.account_type === "credit_card" ? " (consider: credit card)" : ""}</option>
            <option value="bank">Bank account</option><option value="credit_card">Credit card</option>
          </Select>
        </Field>
        <Field label="PDF password (if protected)" hint="Used once to open the file; never stored.">
          <Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Parser">
          <Select value={parser} onChange={(e) => setParser(e.target.value)}>
            <option value="">Automatic (best match)</option>
            {parsers.data?.parsers.map((p: any) => <option key={p.name} value={p.name}>{p.name} v{p.version}{p.is_generic ? " (generic)" : ""}</option>)}
          </Select>
        </Field>
        <label className="flex items-center gap-2 self-end pb-2 text-sm">
          <input type="checkbox" checked={forceOcr} onChange={(e) => setForceOcr(e.target.checked)} disabled={!parsers.data?.ocr_available} />
          Force local OCR {parsers.data && !parsers.data.ocr_available && <span className="text-xs text-subtle">(Tesseract not installed)</span>}
        </label>
      </div>
      <ErrorBox error={upload.error} />
      <Button type="submit" variant="primary" loading={upload.isPending} disabled={!file}><FileUp className="h-4 w-4" />Upload and preview</Button>
      <p className="text-xs text-subtle">Nothing is added to your ledger until you review the preview and confirm.</p>
    </form>
  );
}

function UploadAndHistory() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const history = useQuery({ queryKey: ["imports"], queryFn: () => api.get<Paged<Batch>>("/imports", { page_size: 100 }) });
  const accounts = useAccounts();
  const parsers = useQuery({ queryKey: ["parsers"], queryFn: () => api.get<any>("/imports/parsers") });
  const name = (id: number | null) => accounts.data?.find((a) => a.id === id)?.name ?? "—";
  return (
    <>
      <PageHeader title="Import statements" description="Upload → preview → correct → confirm. Repeated and overlapping statements are safe." />
      <Card title="Upload a statement"><UploadForm initialAccount={sp.get("account") ?? undefined} onDone={(b) => nav(`/import/${b.id}`)} /></Card>

      <Card title="Supported formats" className="mt-4" subtitle="Only formats tested against real samples are listed as institution-specific.">
        <ul className="space-y-1 text-sm">
          {parsers.data?.parsers.map((p: any) => (
            <li key={p.name}><b>{p.name}</b> v{p.version} — {p.description}
              {p.tested_variants.length > 0 && <span className="text-xs text-subtle"> Tested: {p.tested_variants.join(", ")}</span>}</li>
          ))}
        </ul>
        {parsers.data && parsers.data.parsers.every((p: any) => p.is_generic) && (
          <p className="mt-2 text-xs text-subtle">No bank-specific parsers yet. Generic parsing handles most CSV/Excel exports and many PDFs; share a
            redacted sample of any format that fails so a dedicated, tested parser can be added.</p>
        )}
      </Card>

      <Card title="Import history" className="mt-4">
        {history.isLoading ? <Spinner /> : !history.data?.items.length ? <p className="text-sm text-subtle">No imports yet.</p> : (
          <Table>
            <thead><tr><th>#</th><th>File</th><th>Account</th><th>Period</th><th>Parser</th><th className="text-right">Accepted / extracted</th><th className="text-right">Dupes</th><th>Status</th><th>When</th></tr></thead>
            <tbody>{history.data.items.map((b) => (
              <tr key={b.id}>
                <td><Link className="text-primary hover:underline" to={`/import/${b.id}`}>{b.id}</Link></td>
                <td className="max-w-[16rem] truncate">{b.filename}{b.repeat_of_batch_id && <Badge tone="warn">repeat of #{b.repeat_of_batch_id}</Badge>}</td>
                <td>{name(b.account_id)}</td>
                <td className="whitespace-nowrap text-xs">{fmtDate(b.statement_meta.period_start)} – {fmtDate(b.statement_meta.period_end)}</td>
                <td className="text-xs">{b.parser_name} {b.parser_version}</td>
                <td className="num text-right">{b.row_counts.accepted ?? b.row_counts.to_import ?? 0} / {b.row_counts.extracted ?? 0}</td>
                <td className="num text-right">{b.row_counts.duplicates_skipped ?? b.row_counts.exact_duplicates ?? 0}</td>
                <td><Status status={b.status} /></td>
                <td className="whitespace-nowrap text-xs">{fmtDateTime(b.committed_at ?? b.created_at)}</td>
              </tr>))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ preview */

const FILTERS = [["", "All rows"], ["errors", "Errors"], ["warnings", "Warnings"], ["duplicates", "Duplicates"], ["excluded", "Excluded"]] as const;

function Preview({ id }: { id: number }) {
  const nav = useNavigate();
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["import", id, filter], queryFn: () => api.get<Batch>(`/imports/${id}`, { rows: filter || undefined, page_size: 500 }) });
  const accounts = useAccounts();
  const [editRow, setEditRow] = useState<ImportRow | null>(null);
  const [confirmCommit, setConfirmCommit] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [profileName, setProfileName] = useState("");
  const setAccount = useMut((aid: number) => api.post(`/imports/${id}/account`, { account_id: aid }));
  const toggle = useMut((r: ImportRow) => api.patch(`/imports/${id}/rows/${r.id}`, { include: !r.include }));
  const commit = useMut(() => api.post<Batch>(`/imports/${id}/commit`), () => setConfirmCommit(false));
  const discard = useMut(() => api.post(`/imports/${id}/discard`), () => nav("/import"));
  const impact = useQuery({ queryKey: ["impact", id], enabled: confirmDelete, queryFn: () => api.get<any>(`/imports/${id}/deletion-impact`) });
  const remove = useMut(() => api.del(`/imports/${id}`, { confirm_linked: true }), () => setConfirmDelete(false));
  const reprocess = useMut(() => api.post<Batch>(`/imports/${id}/reprocess`, {}), (b) => nav(`/import/${b.id}`));
  const saveProfile = useMut(() => api.post(`/imports/${id}/save-profile`, { name: profileName }), () => setProfileName(""));
  const reparse = useMut((body: Record<string, unknown>) => api.post(`/imports/${id}/reparse`, body));

  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const b = q.data!;
  const v = b.validation ?? ({} as Batch["validation"]);
  const m = b.statement_meta ?? {};
  const isPreview = b.status === "preview";
  const acct = accounts.data?.find((a) => a.id === b.account_id);
  const rc = b.row_counts ?? {};

  return (
    <>
      <PageHeader title={`Import #${b.id}: ${b.filename}`}
        description={<>Parser <b>{b.parser_name ?? "—"} {b.parser_version}</b>{b.parser_confidence != null && ` (confidence ${Math.round(b.parser_confidence * 100)}%)`} · {b.file_type.toUpperCase()}
          {b.extraction_info?.ocr_used ? " · OCR" : ""} · uploaded {fmtDateTime(b.created_at)}</>}
        actions={<>
          <Status status={b.status} />
          <Button onClick={() => nav("/import")}>Back</Button>
          {isPreview && <Button variant="ghost" loading={discard.isPending} onClick={() => discard.mutate(undefined)}>Discard</Button>}
          {b.status === "committed" && <>
            <Button onClick={() => nav(`/transactions?import_batch_id=${b.id}`)}>View transactions</Button>
            {b.has_file && <Button loading={reprocess.isPending} onClick={() => reprocess.mutate(undefined)}><RefreshCw className="h-4 w-4" />Reprocess</Button>}
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4" />Delete import</Button>
          </>}
        </>} />

      {b.status === "failed" && (
        <Card title="Import failed">
          <Notice tone="bad">{b.error_message}</Notice>
          {(b.extraction_info?.error_code === "pdf_password_required" || b.extraction_info?.error_code === "pdf_password_incorrect") && (
            <p className="mt-2 text-sm">Upload the file again with its password:</p>
          )}
          <div className="mt-3"><UploadForm initialAccount={b.account_id ? String(b.account_id) : undefined} onDone={(nb) => nav(`/import/${nb.id}`)} /></div>
        </Card>
      )}

      {b.status !== "failed" && <>
        <div className="space-y-2">
          {b.warnings.map((w) => <Notice key={w}>{w}</Notice>)}
          {b.status === "committed" && <Notice tone="good">Imported {rc.accepted ?? 0} transaction(s); {rc.duplicates_skipped ?? 0} duplicate(s) skipped; {rc.rejected ?? 0} error row(s) not imported; {rc.match_suggestions ?? 0} match suggestion(s) created. <Link to="/reconciliation" className="text-primary underline">Review matches</Link></Notice>}
          {commit.error && <ErrorBox error={commit.error} />}
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <Card title="Account">
            {isPreview ? (
              <Field label="Import into" hint={m.account_suggested ? "Suggested from the account number on the statement — confirm it." : m.account_hint ? `Statement shows account ${m.account_hint}` : undefined}>
                <Select value={b.account_id ?? ""} onChange={(e) => setAccount.mutate(Number(e.target.value))}>
                  <option value="" disabled>Choose an account…</option>
                  {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name} ({ACCOUNT_TYPE_LABELS[a.account_type]})</option>)}
                </Select>
              </Field>
            ) : <p className="text-sm">{acct?.name}</p>}
            <p className="mt-2 text-xs text-subtle">Detected type: {b.detected_statement_type ?? "—"}{m.account_hint && ` · account ${m.account_hint}`}</p>
          </Card>
          <StatementCard b={b} editable={isPreview} />
          <Card title="Validation">
            <dl className="grid grid-cols-[1fr_auto] gap-y-1 text-sm">
              <dt className="text-subtle">Rows extracted</dt><dd className="num text-right">{rc.extracted ?? 0}</dd>
              <dt className="text-subtle">Will import</dt><dd className="num text-right font-semibold">{rc.to_import ?? rc.accepted ?? 0}</dd>
              <dt className="text-subtle">Errors (not imported)</dt><dd className="num text-right">{rc.errors ?? 0}</dd>
              <dt className="text-subtle">Exact duplicates (skipped)</dt><dd className="num text-right">{rc.exact_duplicates ?? 0}</dd>
              <dt className="text-subtle">Possible duplicates (review)</dt><dd className="num text-right">{rc.possible_duplicates ?? 0}</dd>
              <dt className="text-subtle">Total debits / credits</dt><dd className="num text-right">₹{v.total_debits} / ₹{v.total_credits}</dd>
              <dt className="text-subtle">Running balance chain</dt><dd className="text-right"><Status status={v.running_balance_check} /></dd>
              <dt className="text-subtle">Opening + movements = closing</dt><dd className="text-right"><Status status={v.balance_check} /></dd>
              <dt className="text-subtle">Calculated closing</dt><dd className="num text-right">{v.closing_balance_calculated ? `₹${v.closing_balance_calculated}` : "—"}</dd>
              <dt className="text-subtle">Reported closing</dt><dd className="num text-right">{v.closing_balance_reported ? `₹${v.closing_balance_reported}` : "—"}</dd>
              {v.closing_difference && v.closing_difference !== "0" && v.closing_difference !== "0.00" && <><dt className="font-medium text-negative">Difference</dt><dd className="num text-right font-semibold text-negative">₹{v.closing_difference}</dd></>}
            </dl>
            {v.messages?.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-subtle">{v.messages.map((x) => <li key={x}>{x}</li>)}</ul>}
            {v.sign_hint === "inverted" && isPreview && (
              <Button size="sm" className="mt-2" loading={reparse.isPending} onClick={() => reparse.mutate({ sign_mode: "inverted", column_mapping: stripSign(m.mapping_used) })}>
                Re-read with positive = money out</Button>
            )}
          </Card>
        </div>

        {isPreview && (m.needs_mapping || (b.rows_total === 0 && !filter)) && <MappingCard b={b} onApply={(body) => reparse.mutate(body)} loading={reparse.isPending} error={reparse.error} />}

        <Card className="mt-4" title="Extracted rows" subtitle="Check dates, descriptions and signs against the original statement. Click a row to correct it."
          actions={<div className="flex gap-1">{FILTERS.map(([k, label]) => <Button key={k} size="sm" variant={filter === k ? "primary" : "secondary"} onClick={() => setFilter(k)}>{label}</Button>)}</div>}>
          {b.rows?.length ? (
            <Table>
              <thead><tr><th>Import?</th><th>#</th><th>Date</th><th>Description</th><th className="text-right">Debit</th><th className="text-right">Credit</th><th className="text-right">Signed</th><th className="text-right">Balance</th><th>Checks</th></tr></thead>
              <tbody>{b.rows.map((r) => (
                <tr key={r.id} className={r.status === "error" ? "bg-negative/5" : r.duplicate_status === "exact" ? "opacity-60" : ""}>
                  <td><input type="checkbox" aria-label={`Include row ${r.row_index + 1}`} checked={r.include} disabled={!isPreview || r.status === "error"} onChange={() => toggle.mutate(r)} /></td>
                  <td className="num text-xs text-subtle" title={r.source_ref ?? ""}>{r.row_index + 1}</td>
                  <td className="whitespace-nowrap">{fmtDate(r.txn_date)}</td>
                  <td className="max-w-md">{isPreview ? <button className="focus-ring rounded text-left hover:underline" onClick={() => setEditRow(r)}>{r.description || <i>empty</i>}</button> : r.description}
                    {r.reference && <div className="text-xs text-subtle">Ref {r.reference}</div>}</td>
                  <td className="text-right"><Money minor={r.debit_minor} /></td>
                  <td className="text-right"><Money minor={r.credit_minor} /></td>
                  <td className="text-right font-medium"><Money minor={r.amount_minor} colored /></td>
                  <td className="text-right text-xs"><Money minor={r.balance_minor} /></td>
                  <td className="space-x-1 text-xs">
                    {r.errors.map((e) => <Badge key={e} tone="bad">{e}</Badge>)}
                    {r.warnings.map((w) => <Badge key={w} tone="warn">{w}</Badge>)}
                    {r.duplicate_status === "exact" && <Badge title={`Already in ledger as #${r.duplicate_of_transaction_id}`}>Duplicate of #{r.duplicate_of_transaction_id}</Badge>}
                    {r.duplicate_status === "possible" && <Badge tone="warn" title="Same amount within a few days — verify">Possible duplicate of #{r.duplicate_of_transaction_id}</Badge>}
                    {r.user_edited && <Badge tone="info">edited</Badge>}
                  </td>
                </tr>))}
              </tbody>
            </Table>
          ) : <p className="text-sm text-subtle">No rows {filter ? "match this filter" : "were extracted"}.</p>}
          {(m.ignored_line_count ?? 0) > 0 && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer text-subtle">{m.ignored_line_count} non-transaction line(s) were recognised and skipped (headers, totals, footers) — show</summary>
              <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto">{m.ignored_lines?.map((l, i) => <li key={i}><span className="text-subtle">{l.ref} · {l.reason}:</span> {l.text}</li>)}</ul>
            </details>
          )}
        </Card>

        {isPreview && (
          <div className="sticky bottom-0 mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3 shadow-lg">
            <Button variant="primary" disabled={!b.account_id || !(rc.to_import >= 0)} onClick={() => setConfirmCommit(true)}>Confirm import of {rc.to_import ?? 0} transaction(s)</Button>
            {!b.account_id && <span className="text-sm text-warning">Choose an account first.</span>}
            {m.mapping_used && (
              <div className="ml-auto flex items-center gap-2">
                <Input className="w-56" placeholder="Save this format as… (e.g. ICICI CSV)" value={profileName} onChange={(e) => setProfileName(e.target.value)} aria-label="Profile name" />
                <Button disabled={!profileName} loading={saveProfile.isPending} onClick={() => saveProfile.mutate(undefined)}>Save format</Button>
              </div>
            )}
            <ErrorBox error={saveProfile.error} />
            {saveProfile.isSuccess && <span className="text-sm text-positive">Format saved — future files with these columns will be recognised.</span>}
          </div>
        )}
      </>}

      {editRow && <RowEditor batchId={id} row={editRow} onClose={() => setEditRow(null)} />}
      <Confirm open={confirmCommit} title="Confirm import" confirmLabel="Import" loading={commit.isPending}
        onCancel={() => setConfirmCommit(false)} onConfirm={() => commit.mutate(undefined)}>
        <p>Import <b>{rc.to_import}</b> transaction(s) into <b>{acct?.name}</b>.</p>
        {(rc.errors ?? 0) > 0 && <p className="text-negative">{rc.errors} row(s) with errors will NOT be imported.</p>}
        {(rc.exact_duplicates ?? 0) > 0 && <p>{rc.exact_duplicates} row(s) already in the ledger will be skipped.</p>}
        {(rc.possible_duplicates ?? 0) > 0 && <p className="text-warning">{rc.possible_duplicates} possible duplicate(s) will be imported — untick them if they are the same transaction.</p>}
        {v.balance_check === "failed" && <p className="text-negative">The statement does not reconcile (difference ₹{v.closing_difference}). It will be recorded as a discrepancy; no amounts will be changed.</p>}
        <ErrorBox error={commit.error} />
      </Confirm>
      <Confirm open={confirmDelete} title="Delete this import" danger confirmLabel="Delete import" loading={remove.isPending}
        onCancel={() => setConfirmDelete(false)} onConfirm={() => remove.mutate(undefined)}>
        {impact.data ? <>
          <p>This removes <b>{impact.data.transactions}</b> transaction(s) and the statement record from the ledger. The import history entry is kept.</p>
          {impact.data.approved_relationships > 0 && <p className="text-negative">{impact.data.approved_relationships} approved match(es) with other accounts will also be removed; the other side becomes unmatched.</p>}
          {impact.data.user_edited_transactions > 0 && <p className="text-warning">{impact.data.user_edited_transactions} transaction(s) have your categories or notes, which will be lost.</p>}
        </> : <Spinner />}
        <ErrorBox error={remove.error} />
      </Confirm>
    </>
  );
}

function stripSign(m?: Record<string, string> | null) {
  if (!m) return undefined;
  const { _sign_mode, ...rest } = m;
  void _sign_mode;
  return rest;
}

function StatementCard({ b, editable }: { b: Batch; editable: boolean }) {
  const m = b.statement_meta;
  const [f, setF] = useState({ start: m.period_start ?? "", end: m.period_end ?? "", open: minorToInput(m.opening_balance_minor), close: minorToInput(m.closing_balance_minor) });
  useEffect(() => setF({ start: m.period_start ?? "", end: m.period_end ?? "", open: minorToInput(m.opening_balance_minor), close: minorToInput(m.closing_balance_minor) }),
    [m.period_start, m.period_end, m.opening_balance_minor, m.closing_balance_minor]);
  const save = useMut(() => {
    const o = f.open.trim() ? parseRupees(f.open) : null;
    const c = f.close.trim() ? parseRupees(f.close) : null;
    if ((f.open.trim() && o === null) || (f.close.trim() && c === null)) throw new Error("Balances must be numbers");
    return api.patch(`/imports/${b.id}/statement`, { period_start: f.start || null, period_end: f.end || null, opening_balance_minor: o, closing_balance_minor: c });
  });
  if (!editable) {
    return <Card title="Statement"><p className="text-sm">{fmtDate(m.period_start)} – {fmtDate(m.period_end)}</p>
      <p className="mt-1 text-sm">Opening {inr(m.opening_balance_minor ?? null)} · Closing {inr(m.closing_balance_minor ?? null)}</p></Card>;
  }
  return (
    <Card title="Statement period & balances" subtitle="As printed on the statement. Correct them if extraction missed something.">
      <div className="grid grid-cols-2 gap-2">
        <Field label="From"><Input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
        <Field label="To"><Input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
        <Field label="Opening balance"><Input inputMode="decimal" value={f.open} onChange={(e) => setF({ ...f, open: e.target.value })} placeholder="unknown" /></Field>
        <Field label="Closing balance"><Input inputMode="decimal" value={f.close} onChange={(e) => setF({ ...f, close: e.target.value })} placeholder="unknown" /></Field>
      </div>
      <p className="mt-1 text-xs text-subtle">Credit cards: enter amounts owed as negative (e.g. -25000.00).</p>
      <Button size="sm" className="mt-2" loading={save.isPending} onClick={() => save.mutate(undefined)}>Update</Button>
      <ErrorBox error={save.error} />
    </Card>
  );
}

const ROLES: [string, string][] = [["date", "Transaction date *"], ["description", "Description *"], ["debit", "Debit / withdrawal"], ["credit", "Credit / deposit"],
  ["amount", "Single amount column"], ["drcr", "Dr/Cr indicator"], ["balance", "Running balance"], ["reference", "Reference / UTR"], ["posting_date", "Value / posting date"]];

function MappingCard({ b, onApply, loading, error }: { b: Batch; onApply: (body: Record<string, unknown>) => void; loading: boolean; error: unknown }) {
  const candidates = b.statement_meta.candidate_headers ?? [];
  const [hdrIdx, setHdrIdx] = useState(0);
  const headers = (b.statement_meta.header_columns?.length ? b.statement_meta.header_columns : candidates[hdrIdx]) ?? [];
  const [map, setMap] = useState<Record<string, string>>({});
  const [sign, setSign] = useState("signed");
  const [stype, setStype] = useState(b.detected_statement_type ?? "bank");
  const [dateFmt, setDateFmt] = useState("");
  return (
    <Card className="mt-4" title="Map columns" subtitle="This format was not recognised automatically. Tell the importer which column is which; you can then save the format.">
      {b.file_type === "pdf" && <Notice tone="info">PDF without a recognisable table. If mapping does not help, export the statement as CSV/Excel from net banking, try OCR, or share a redacted sample so a dedicated parser can be built.</Notice>}
      {candidates.length > 1 && !b.statement_meta.header_columns?.length && (
        <Field label="Header row"><Select value={hdrIdx} onChange={(e) => setHdrIdx(Number(e.target.value))}>
          {candidates.map((c, i) => <option key={i} value={i}>{c.filter(Boolean).join(" | ").slice(0, 120)}</option>)}</Select></Field>
      )}
      {headers.length === 0 ? <p className="text-sm text-subtle">No header-like rows were found.</p> : (
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          {ROLES.map(([role, label]) => (
            <Field key={role} label={label}>
              <Select value={map[role] ?? ""} onChange={(e) => setMap({ ...map, [role]: e.target.value })}>
                <option value="">— not present —</option>
                {headers.filter(Boolean).map((h) => <option key={h} value={h}>{h}</option>)}
              </Select>
            </Field>
          ))}
          <Field label="Single amount sign" hint="Only for a single amount column without Dr/Cr">
            <Select value={sign} onChange={(e) => setSign(e.target.value)}>
              <option value="signed">Negative = money out (bank style)</option><option value="inverted">Positive = money out (card style)</option>
            </Select>
          </Field>
          <Field label="Statement type"><Select value={stype} onChange={(e) => setStype(e.target.value)}><option value="bank">Bank</option><option value="credit_card">Credit card</option></Select></Field>
          <Field label="Date format (optional)" hint="e.g. %d/%m/%Y — leave empty to auto-detect day-first"><Input value={dateFmt} onChange={(e) => setDateFmt(e.target.value)} /></Field>
        </div>
      )}
      <ErrorBox error={error} />
      <Button className="mt-3" variant="primary" loading={loading} disabled={!map.date || !map.description || !(map.amount || map.debit || map.credit)}
        onClick={() => onApply({ column_mapping: map, sign_mode: sign, statement_type: stype, date_format: dateFmt || undefined })}>Apply mapping</Button>
    </Card>
  );
}

function RowEditor({ batchId, row, onClose }: { batchId: number; row: ImportRow; onClose: () => void }) {
  const [f, setF] = useState({ txn_date: row.txn_date ?? "", description: row.description ?? "", amount: minorToInput(row.amount_minor), balance: minorToInput(row.balance_minor) });
  const save = useMut(() => api.patch(`/imports/${batchId}/rows/${row.id}`, f), onClose);
  return (
    <Modal open onClose={onClose} title={`Correct row ${row.row_index + 1}`} footer={<><Button onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save correction</Button></>}>
      <div className="space-y-3">
        <div className="rounded bg-muted p-2 text-xs"><p className="mb-1 font-semibold text-subtle">Original extracted values ({row.source_ref})</p>
          <pre className="whitespace-pre-wrap break-all">{JSON.stringify(row.raw, null, 1)}</pre></div>
        <Field label="Date"><Input type="date" value={f.txn_date} onChange={(e) => setF({ ...f, txn_date: e.target.value })} /></Field>
        <Field label="Description"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Signed amount (₹)" hint="Negative = money out / you owe more. Positive = money in / you owe less.">
          <Input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Running balance (₹, optional)"><Input inputMode="decimal" value={f.balance} onChange={(e) => setF({ ...f, balance: e.target.value })} /></Field>
        <ErrorBox error={save.error} />
      </div>
    </Modal>
  );
}
