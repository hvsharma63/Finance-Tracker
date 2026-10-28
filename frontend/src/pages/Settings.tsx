import { useQuery } from "@tanstack/react-query";
import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { CategorySelect } from "@/components/CategorySelect";
import { Badge, Button, Card, Confirm, ErrorBox, Field, Input, Notice, PageHeader, Select, Spinner, Status, Table } from "@/components/ui";
import { api, download } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useCategories, useMut } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
const TABS = ["Categories", "Rules", "Merchants", "Matching", "Formats", "PDF passwords", "Backups", "Security", "Audit log"];
const REPORTING = ["income", "expense", "transfer", "investment", "loan_principal", "refund", "cash_withdrawal", "excluded"];

export default function Settings() {
  const [tab, setTab] = useState("Categories");
  return (
    <>
      <PageHeader title="Settings" />
      <div className="mb-4 flex flex-wrap gap-1" role="tablist">
        {TABS.map((t) => <Button key={t} role="tab" aria-selected={tab === t} size="sm" variant={tab === t ? "primary" : "secondary"} onClick={() => setTab(t)}>{t}</Button>)}
      </div>
      {tab === "Categories" && <Categories />}
      {tab === "Rules" && <Rules />}
      {tab === "Merchants" && <Merchants />}
      {tab === "Matching" && <Matching />}
      {tab === "Formats" && <Formats />}
      {tab === "PDF passwords" && <PdfPasswords />}
      {tab === "Backups" && <Backups />}
      {tab === "Security" && <Security />}
      {tab === "Audit log" && <Audit />}
    </>
  );
}

function Categories() {
  const cats = useCategories();
  const [f, setF] = useState({ name: "", parent_id: "", reporting_type: "expense" });
  const create = useMut(() => api.post("/categories", { name: f.name, parent_id: f.parent_id ? Number(f.parent_id) : null, reporting_type: f.reporting_type }), () => setF({ ...f, name: "" }));
  const patch = useMut((v: { id: number; body: any }) => api.patch(`/categories/${v.id}`, v.body));
  if (cats.isLoading) return <Spinner />;
  const parents = cats.data!.filter((c) => !c.parent_id);
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card title="Categories" className="xl:col-span-2" subtitle="The reporting type decides whether a category counts as income, spending, or a financial movement.">
        <ErrorBox error={patch.error} />
        <Table>
          <thead><tr><th>Category</th><th>Reporting type</th><th className="text-right">Transactions</th><th>Active</th></tr></thead>
          <tbody>{parents.flatMap((p) => [p, ...cats.data!.filter((c) => c.parent_id === p.id)]).map((c) => (
            <tr key={c.id}>
              <td className={c.parent_id ? "pl-8" : "font-semibold"}>{c.name}</td>
              <td><Select aria-label={`Reporting type for ${c.name}`} className="h-8 w-44" value={c.reporting_type} onChange={(e) => patch.mutate({ id: c.id, body: { reporting_type: e.target.value } })}>
                {REPORTING.map((r) => <option key={r}>{r}</option>)}</Select></td>
              <td className="num text-right">{c.transaction_count}</td>
              <td><input type="checkbox" aria-label={`Active ${c.name}`} checked={c.is_active} onChange={(e) => patch.mutate({ id: c.id, body: { is_active: e.target.checked } })} /></td>
            </tr>))}
          </tbody>
        </Table>
      </Card>
      <Card title="Add category">
        <div className="space-y-3">
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Parent"><Select value={f.parent_id} onChange={(e) => setF({ ...f, parent_id: e.target.value })}>
            <option value="">— top level —</option>{parents.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
          <Field label="Reporting type"><Select value={f.reporting_type} onChange={(e) => setF({ ...f, reporting_type: e.target.value })}>{REPORTING.map((r) => <option key={r}>{r}</option>)}</Select></Field>
          <ErrorBox error={create.error} />
          <Button variant="primary" disabled={!f.name} loading={create.isPending} onClick={() => create.mutate(undefined)}>Add</Button>
        </div>
      </Card>
    </div>
  );
}

const FIELDS = ["description", "merchant", "reference", "transaction_type", "direction", "abs_amount", "account_id"];
const OPS = ["contains", "not_contains", "equals", "starts_with", "regex", "gt", "gte", "lt", "lte"];

function Rules() {
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api.get<any[]>("/rules") });
  const cats = useCategories();
  const [name, setName] = useState("");
  const [cat, setCat] = useState<number | null>(null);
  const [priority, setPriority] = useState("100");
  const [match, setMatch] = useState("all");
  const [conds, setConds] = useState([{ field: "description", op: "contains", value: "" }]);
  const [testResult, setTestResult] = useState<any>(null);
  const conditions = () => ({ match, conditions: conds.map((c) => ({ ...c, value: ["abs_amount", "account_id"].includes(c.field) ? Math.round(Number(c.value) * (c.field === "abs_amount" ? 100 : 1)) : c.value })) });
  const test = useMut(() => api.post<any>("/rules/test", { conditions: conditions() }), setTestResult);
  const create = useMut(() => api.post<any>("/rules", { name, category_id: cat, priority: Number(priority), conditions: conditions() }), () => { setName(""); setTestResult(null); });
  const patch = useMut((v: { id: number; body: any }) => api.patch(`/rules/${v.id}`, v.body));
  const del = useMut((id: number) => api.del(`/rules/${id}`));
  const reapply = useMut(() => api.post<any>("/rules/reapply"));
  const catName = (id: number) => cats.data?.find((c) => c.id === id)?.name;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Rules" subtitle="Run in priority order (lowest first); the first match wins. Your manual categories are never overwritten."
        actions={<Button size="sm" loading={reapply.isPending} onClick={() => reapply.mutate(undefined)}>Re-run on all</Button>}>
        {reapply.data && <p className="mb-2 text-xs text-subtle">{reapply.data.categorized} transaction(s) categorized.</p>}
        {!rules.data?.length ? <p className="text-sm text-subtle">No rules yet. Categorize a transaction and accept the rule suggestion, or add one here.</p> : (
          <Table><thead><tr><th>Priority</th><th>Rule</th><th>Category</th><th>On</th><th /></tr></thead>
            <tbody>{rules.data.map((r) => (
              <tr key={r.id}><td className="num">{r.priority}</td><td>{r.name}<div className="text-xs text-subtle">{r.conditions.conditions.map((c: any) => `${c.field} ${c.op} ${c.value}`).join(r.conditions.match === "all" ? " AND " : " OR ")}</div></td>
                <td>{catName(r.category_id)}</td>
                <td><input type="checkbox" aria-label="Enabled" checked={r.enabled} onChange={(e) => patch.mutate({ id: r.id, body: { enabled: e.target.checked } })} /></td>
                <td><Button size="sm" variant="ghost" aria-label="Delete rule" onClick={() => del.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>))}
            </tbody></Table>
        )}
      </Card>
      <Card title="New rule">
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Category"><CategorySelect value={cat} onChange={setCat} noneLabel="Choose…" /></Field>
            <Field label="Priority"><Input value={priority} onChange={(e) => setPriority(e.target.value)} /></Field>
          </div>
          <Field label="Match"><Select value={match} onChange={(e) => setMatch(e.target.value)}><option value="all">All conditions</option><option value="any">Any condition</option></Select></Field>
          {conds.map((c, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1.5fr_auto] gap-2">
              <Select aria-label="Field" value={c.field} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))}>{FIELDS.map((f) => <option key={f}>{f}</option>)}</Select>
              <Select aria-label="Operator" value={c.op} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>{OPS.map((f) => <option key={f}>{f}</option>)}</Select>
              <Input aria-label="Value" placeholder={c.field === "abs_amount" ? "₹ amount" : c.field === "direction" ? "debit / credit" : "text"} value={c.value} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
              <Button size="sm" variant="ghost" aria-label="Remove condition" disabled={conds.length === 1} onClick={() => setConds(conds.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <Button size="sm" onClick={() => setConds([...conds, { field: "description", op: "contains", value: "" }])}>Add condition</Button>
          <ErrorBox error={test.error || create.error} />
          {testResult && <Notice tone="info">Matches {testResult.match_count} existing transaction(s){testResult.sample.length ? `, e.g. ${testResult.sample.slice(0, 3).map((s: any) => s.description).join("; ")}` : ""}.</Notice>}
          <div className="flex gap-2">
            <Button loading={test.isPending} onClick={() => test.mutate(undefined)}>Test</Button>
            <Button variant="primary" disabled={!name || !cat} loading={create.isPending} onClick={() => create.mutate(undefined)}>Create & apply to uncategorized</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Merchants() {
  const q = useQuery({ queryKey: ["aliases"], queryFn: () => api.get<any[]>("/merchant-aliases") });
  const [f, setF] = useState({ pattern: "", match_type: "contains", merchant_name: "" });
  const create = useMut(() => api.post("/merchant-aliases", f), () => setF({ pattern: "", match_type: "contains", merchant_name: "" }));
  const del = useMut((id: number) => api.del(`/merchant-aliases/${id}`));
  return (
    <Card title="Merchant aliases" subtitle="Normalize messy narrations to one merchant name (e.g. 'SWIGGY*BANGALORE' → Swiggy). Applied to all transactions.">
      <div className="mb-3 grid gap-2 sm:grid-cols-4">
        <Input aria-label="Pattern" placeholder="Text in description" value={f.pattern} onChange={(e) => setF({ ...f, pattern: e.target.value })} />
        <Select aria-label="Match type" value={f.match_type} onChange={(e) => setF({ ...f, match_type: e.target.value })}><option>contains</option><option>exact</option><option>regex</option></Select>
        <Input aria-label="Merchant name" placeholder="Merchant name" value={f.merchant_name} onChange={(e) => setF({ ...f, merchant_name: e.target.value })} />
        <Button variant="primary" disabled={!f.pattern || !f.merchant_name} loading={create.isPending} onClick={() => create.mutate(undefined)}>Add alias</Button>
      </div>
      <ErrorBox error={create.error} />
      <Table><tbody>{q.data?.map((a) => <tr key={a.id}><td>{a.match_type} “{a.pattern}”</td><td>→ {a.merchant_name}</td>
        <td><Button size="sm" variant="ghost" aria-label="Delete alias" onClick={() => del.mutate(a.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>)}</tbody></Table>
    </Card>
  );
}

function Matching() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api.get<any>("/settings") });
  const [vals, setVals] = useState<Record<string, string>>({});
  const save = useMut(() => api.patch("/settings", { values: Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, k.endsWith("_minor") ? Math.round(Number(v) * 100) : Number(v)])) }), () => setVals({}));
  if (!q.data) return <Spinner />;
  const v = q.data.values;
  return (
    <Card title="Matching & duplicate detection">
      <div className="grid max-w-2xl gap-3 sm:grid-cols-3">
        <Field label="Match window (days)" hint="Transfers/payments up to this many days apart"><Input defaultValue={v.matching_window_days} onChange={(e) => setVals({ ...vals, matching_window_days: e.target.value })} /></Field>
        <Field label="Amount tolerance (₹)" hint="For fees deducted in transit; 0 = exact"><Input defaultValue={v.matching_amount_tolerance_minor / 100} onChange={(e) => setVals({ ...vals, matching_amount_tolerance_minor: e.target.value })} /></Field>
        <Field label="Possible-duplicate window (days)"><Input defaultValue={v.possible_duplicate_window_days} onChange={(e) => setVals({ ...vals, possible_duplicate_window_days: e.target.value })} /></Field>
      </div>
      <ErrorBox error={save.error} />
      <Button className="mt-3" variant="primary" disabled={!Object.keys(vals).length} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button>
    </Card>
  );
}

function Formats() {
  const parsers = useQuery({ queryKey: ["parsers"], queryFn: () => api.get<any>("/imports/parsers") });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<any[]>("/parser-profiles") });
  const del = useMut((id: number) => api.del(`/parser-profiles/${id}`));
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Built-in parsers">
        <Table><thead><tr><th>Parser</th><th>Version</th><th>Files</th><th>Tested variants</th></tr></thead>
          <tbody>{parsers.data?.parsers.map((p: any) => <tr key={p.name}><td>{p.name}{p.is_generic && <Badge>generic</Badge>}<div className="text-xs text-subtle">{p.description}</div></td>
            <td>{p.version}</td><td className="text-xs">{p.file_types.join(", ")}</td><td className="text-xs">{p.tested_variants.join(", ") || "—"}</td></tr>)}</tbody></Table>
        <p className="mt-2 text-xs text-subtle">OCR (Tesseract): {parsers.data?.ocr_available ? "available" : "not installed"}</p>
      </Card>
      <Card title="Saved formats (your column mappings)" subtitle="Files whose header row matches a saved format are imported with it automatically.">
        {!profiles.data?.length ? <p className="text-sm text-subtle">None saved. After mapping an unrecognised file during import, save it as a format.</p> : (
          <Table><tbody>{profiles.data.map((p) => <tr key={p.id}><td>{p.name} <span className="text-xs text-subtle">v{p.version} · {p.file_type} · {p.statement_type}</span>
            <div className="text-xs text-subtle">{Object.entries(p.column_mapping).map(([k, v]) => `${k}=${v}`).join(", ")}</div></td>
            <td><Button size="sm" variant="ghost" aria-label="Delete format" onClick={() => del.mutate(p.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>)}</tbody></Table>
        )}
      </Card>
    </div>
  );
}

function Backups() {
  const q = useQuery({ queryKey: ["backups"], queryFn: () => api.get<any>("/backups") });
  const create = useMut(() => api.post<any>("/backups", { include_documents: true }));
  const [restoreName, setRestoreName] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [inspect, setInspect] = useState<any>(null);
  const restore = useMut(() => {
    const fd = new FormData();
    if (file) fd.append("file", file); else fd.append("filename", restoreName!);
    fd.append("confirm", "true");
    return api.post<any>("/backups/restore", fd);
  }, () => { setRestoreName(null); setFile(null); });
  const check = useMut(() => { const fd = new FormData(); fd.append("file", file!); return api.post<any>("/backups/inspect", fd); }, setInspect);
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Create backup" subtitle={`Saved to ${q.data?.backup_dir ?? "…"}`}>
        <p className="mb-3 text-sm text-subtle">Includes every table and all stored statement files, with checksums. Sign-in sessions are excluded.</p>
        <Button variant="primary" loading={create.isPending} onClick={() => create.mutate(undefined)}>Create backup now</Button>
        <ErrorBox error={create.error} />
        {create.data && <div className="mt-3"><Notice tone="good">Backup {create.data.filename} created and verified ({Math.round(create.data.size_bytes / 1024)} KB, {create.data.details.documents} document(s)).</Notice></div>}
        <Table className="mt-4"><thead><tr><th>File</th><th>Size</th><th /></tr></thead>
          <tbody>{q.data?.files.map((f: any) => <tr key={f.filename}><td className="text-xs">{f.filename}</td><td className="num text-xs">{Math.round(f.size_bytes / 1024)} KB</td>
            <td className="whitespace-nowrap"><Button size="sm" variant="ghost" onClick={() => download(`/backups/${f.filename}/download`)}><Download className="h-4 w-4" /></Button>
              <Button size="sm" onClick={() => setRestoreName(f.filename)}>Restore…</Button></td></tr>)}</tbody></Table>
      </Card>
      <Card title="Restore from a backup file">
        <Field label="Backup ZIP"><Input type="file" accept=".zip" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setInspect(null); }} /></Field>
        <div className="mt-2 flex gap-2">
          <Button disabled={!file} loading={check.isPending} onClick={() => check.mutate(undefined)}>Validate</Button>
          <Button variant="danger" disabled={!file || !inspect?.valid} onClick={() => setRestoreName(file!.name)}>Restore…</Button>
        </div>
        <ErrorBox error={check.error} />
        {inspect && <div className="mt-3"><Notice tone={inspect.valid ? "good" : "bad"}>{inspect.valid ? "Valid backup" : inspect.problems.join("; ")} · created {fmtDateTime(inspect.created_at)} · schema {inspect.schema_revision} · {Object.values(inspect.tables as Record<string, any>).reduce((a: number, t: any) => a + t.rows, 0)} rows</Notice></div>}
        <h3 className="mt-5 text-sm font-semibold">History</h3>
        <Table><tbody>{q.data?.history.map((h: any) => <tr key={h.id}><td className="text-xs">{fmtDateTime(h.at)}</td><td>{h.kind}</td><td><Status status={h.status === "success" ? "passed" : "failed"} /></td><td className="text-xs">{h.filename}</td></tr>)}</tbody></Table>
      </Card>
      <Confirm open={!!restoreName} title="Restore backup — replaces ALL data" danger confirmLabel="Replace all data" loading={restore.isPending}
        onCancel={() => setRestoreName(null)} onConfirm={() => restore.mutate(undefined)}>
        <p>Every account, transaction, import and setting will be replaced with the contents of <b>{restoreName}</b>. This cannot be undone.</p>
        <p>Create a fresh backup first if you may need the current data.</p>
        <ErrorBox error={restore.error} />
        {restore.data && <Notice tone="good">Restore complete.</Notice>}
      </Confirm>
    </div>
  );
}

function Security() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api.get<any>("/settings") });
  const [f, setF] = useState({ current_password: "", new_password: "" });
  const change = useMut(() => api.post("/auth/change-password", f), () => setF({ current_password: "", new_password: "" }));
  const s = q.data?.system;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="System">
        {s && <dl className="grid grid-cols-[12rem_1fr] gap-y-1.5 text-sm">
          <dt className="text-subtle">External connections</dt><dd>{s.external_services}</dd>
          <dt className="text-subtle">Authentication</dt><dd>{s.auth_enabled ? "Enabled" : "Disabled (local mode)"}</dd>
          <dt className="text-subtle">Encryption at rest</dt><dd>{s.encryption_at_rest}</dd>
          <dt className="text-subtle">OCR</dt><dd>{s.ocr_available ? "Tesseract available" : s.ocr_enabled ? "Enabled, Tesseract not found" : "Disabled"}</dd>
          <dt className="text-subtle">Statement storage</dt><dd className="break-all text-xs">{s.storage_dir}</dd>
          <dt className="text-subtle">Document retention</dt><dd>{s.document_retention_days ? `${s.document_retention_days} days` : "Kept until you delete them"}</dd>
          <dt className="text-subtle">Timezone / currency</dt><dd>{s.timezone} · {s.base_currency}</dd>
        </dl>}
      </Card>
      {s?.auth_enabled && <Card title="Change password">
        <div className="space-y-3">
          <Field label="Current password"><Input type="password" autoComplete="current-password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
          <Field label="New password (10+ characters)"><Input type="password" autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
          <ErrorBox error={change.error} />{change.isSuccess && <Notice tone="good">Password changed.</Notice>}
          <Button variant="primary" loading={change.isPending} onClick={() => change.mutate(undefined)}>Change password</Button>
        </div>
      </Card>}
    </div>
  );
}

function Audit() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api.get<any[]>("/audit", { limit: 300 }) });
  if (!q.data) return <Spinner />;
  return (
    <Card title="Audit log" subtitle="Most recent 300 events">
      <Table><thead><tr><th>When</th><th>Entity</th><th>Action</th><th>Details</th></tr></thead>
        <tbody>{q.data.map((e) => <tr key={e.id}><td className="whitespace-nowrap text-xs">{fmtDateTime(e.at)}</td><td className="text-xs">{e.entity_type} #{e.entity_id}</td>
          <td>{e.action}</td><td className="max-w-lg truncate text-xs text-subtle">{JSON.stringify(e.details)}</td></tr>)}</tbody></Table>
    </Card>
  );
}

function PdfPasswords() {
  const q = useQuery({ queryKey: ["pdf-passwords"], queryFn: () => api.get<any[]>("/pdf-passwords") });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<any[]>("/accounts") });
  const [f, setF] = useState({ label: "", password: "", account_id: "" });
  const add = useMut(() => api.post("/pdf-passwords", { label: f.label, password: f.password,
    account_id: f.account_id ? Number(f.account_id) : null }), () => setF({ label: "", password: "", account_id: "" }));
  const del = useMut((id: number) => api.del(`/pdf-passwords/${id}`));
  const name = (id: number | null) => accounts.data?.find((a) => a.id === id)?.name ?? "Any account";
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Saved PDF passwords" subtitle="Tried automatically when a password-protected statement is uploaded. Passwords are encrypted with your SECRET_KEY and are never shown again.">
        {!q.data?.length ? <p className="text-sm text-subtle">None saved yet. Passwords you type during an import are remembered automatically unless you untick the option.</p> : (
          <Table><thead><tr><th>Label</th><th>Account</th><th className="text-right">Used</th><th>Last used</th><th /></tr></thead>
            <tbody>{q.data.map((p) => <tr key={p.id}><td>{p.label}</td><td className="text-xs">{name(p.account_id)}</td>
              <td className="num text-right">{p.use_count}</td><td className="text-xs">{fmtDateTime(p.last_used_at)}</td>
              <td><Button size="sm" variant="ghost" aria-label={`Delete ${p.label}`} onClick={() => del.mutate(p.id)}><Trash2 className="h-4 w-4" /></Button></td></tr>)}</tbody></Table>
        )}
      </Card>
      <Card title="Add a password">
        <div className="space-y-3">
          <Field label="Label"><Input value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="e.g. Axis Bank statements" /></Field>
          <Field label="Password"><Input type="password" autoComplete="off" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          <Field label="Account (optional)" hint="Tried first for this account's statements"><Select value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}>
            <option value="">Any account</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
          <ErrorBox error={add.error} />
          <Button variant="primary" disabled={!f.label || !f.password} loading={add.isPending} onClick={() => add.mutate(undefined)}>Save password</Button>
        </div>
      </Card>
    </div>
  );
}
