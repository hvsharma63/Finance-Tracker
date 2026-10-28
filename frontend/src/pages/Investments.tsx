import { useQuery } from "@tanstack/react-query";
import { Plus, Upload } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, Money, Notice, PageHeader, Select, Spinner, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, inr, parseRupees, todayIso } from "@/lib/format";
import { useAccounts, useMut } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
const INV_TYPES = ["buy", "sell", "dividend", "interest", "reinvestment", "charge", "tax", "split", "bonus", "redemption", "maturity", "transfer_in", "transfer_out"];
const INST_TYPES = ["stock", "etf", "mutual_fund", "bond", "government_security", "fixed_deposit", "other"];

export default function Investments() {
  const pf = useQuery({ queryKey: ["portfolio"], queryFn: () => api.get<any>("/investments/portfolio") });
  const txns = useQuery({ queryKey: ["inv-txns"], queryFn: () => api.get<any[]>("/investments/transactions") });
  const accounts = useAccounts();
  const [modal, setModal] = useState<null | "txn" | "valuation" | "instrument" | "import" | "fd">(null);
  if (pf.isLoading) return <Spinner />;
  if (pf.isError) return <ErrorBox error={pf.error} />;
  const p = pf.data;
  const acctName = (id: number) => accounts.data?.find((a) => a.id === id)?.name ?? id;

  return (
    <>
      <PageHeader title="Investments" description="Cost basis: weighted average. Values come only from dated statement, imported or manual valuations — never invented."
        actions={<>
          <Button onClick={() => setModal("import")}><Upload className="h-4 w-4" />Import CSV/Excel</Button>
          <Button onClick={() => setModal("instrument")}><Plus className="h-4 w-4" />Instrument</Button>
          <Button onClick={() => setModal("txn")}><Plus className="h-4 w-4" />Transaction</Button>
          <Button onClick={() => setModal("valuation")}><Plus className="h-4 w-4" />Valuation</Button>
          <Button onClick={() => setModal("fd")}><Plus className="h-4 w-4" />Fixed deposit</Button>
        </>} />

      {!p.value_complete && <div className="mb-3"><Notice>{p.unvalued_count} holding(s) have no valuation: their current value is unknown. Their cost basis ({inr(p.unvalued_cost_basis_minor)}) is shown separately and is not a market value.</Notice></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Latest known value" value={inr(p.known_value_minor)} sub={`Cost of valued holdings ${inr(p.known_value_cost_basis_minor)}`} />
        <Stat label="Unrealized gain (valued holdings)" value={p.unrealized_gain_minor == null ? "Unknown" : <Money minor={p.unrealized_gain_minor} colored />} />
        <Stat label="Cost basis (all open holdings)" value={inr(p.total_cost_basis_minor)} />
        <Stat label="Realized gains" value={<Money minor={p.realized_gain_minor} colored />} />
        <Stat label="Dividends received" value={inr(p.dividends_minor)} />
        <Stat label="Interest received" value={inr(p.interest_minor)} />
        <Stat label="Principal invested (gross)" value={inr(p.invested_minor)} />
        <Stat label="Principal withdrawn (gross)" value={inr(p.withdrawn_minor)} />
      </div>
      <p className="mt-2 text-xs text-subtle">Time- or money-weighted returns are not shown: they need complete dated cash flows and regular valuations, which imported data does not yet guarantee.</p>

      <Card title="Holdings" className="mt-4">
        {!p.holdings.length ? <Empty title="No holdings">Add instruments and transactions manually or import a CSV/Excel export from your broker or registrar.</Empty> : (
          <Table>
            <thead><tr><th>Instrument</th><th>Account</th><th className="text-right">Quantity</th><th className="text-right">Avg cost</th><th className="text-right">Cost basis</th><th className="text-right">Price</th><th className="text-right">Value</th><th className="text-right">Unrealized</th><th>Valued on</th></tr></thead>
            <tbody>{p.holdings.map((h: any) => (
              <tr key={`${h.account_id}-${h.instrument_id}`}>
                <td>{h.instrument_name}<div className="text-xs text-subtle">{h.identifier} · {h.instrument_type.replace("_", " ")}</div>
                  {h.warnings.map((w: string) => <div key={w} className="text-xs text-warning">{w}</div>)}</td>
                <td className="text-xs">{acctName(h.account_id)}</td>
                <td className="num text-right">{h.quantity}</td>
                <td className="num text-right">{h.average_cost ? `₹${Number(h.average_cost).toFixed(2)}` : "—"}</td>
                <td className="text-right"><Money minor={h.cost_basis_minor} /></td>
                <td className="num text-right">{h.unit_price ? `₹${Number(h.unit_price).toFixed(4)}` : <Badge tone="warn">unknown</Badge>}</td>
                <td className="text-right">{h.value_known ? <Money minor={h.value_minor} /> : <Badge tone="warn">unknown</Badge>}</td>
                <td className="text-right">{h.unrealized_gain_minor == null ? "—" : <Money minor={h.unrealized_gain_minor} colored />}</td>
                <td className="text-xs">{fmtDate(h.valuation_date)} {h.valuation_source && `(${h.valuation_source})`}</td>
              </tr>))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Allocation by type">
          <Table><thead><tr><th>Type</th><th className="text-right">Known value</th><th className="text-right">Cost basis</th><th>Unvalued</th></tr></thead>
            <tbody>{p.allocation.map((a: any) => <tr key={a.instrument_type}><td className="capitalize">{a.instrument_type.replace("_", " ")}</td>
              <td className="text-right"><Money minor={a.value_minor} /></td><td className="text-right"><Money minor={a.cost_basis_minor} /></td><td>{a.unknown_count || ""}</td></tr>)}</tbody></Table>
        </Card>
        <Card title="Fixed deposits" subtitle="Projected interest is not earned until credited">
          {!p.fixed_deposits.length ? <p className="text-sm text-subtle">No fixed deposits. Create an account of type Fixed deposit, then add its details.</p> : (
            <Table><thead><tr><th>Account</th><th className="text-right">Principal</th><th>Rate</th><th>Maturity</th><th className="text-right">Credited interest</th><th className="text-right">Projected interest</th></tr></thead>
              <tbody>{p.fixed_deposits.map((f: any) => <tr key={f.id}><td>{f.account_name}</td><td className="text-right"><Money minor={f.principal_minor} /></td>
                <td>{f.interest_rate ? `${f.interest_rate}%` : "—"}</td><td>{fmtDate(f.maturity_date)}</td>
                <td className="text-right"><Money minor={f.credited_interest_minor} /></td><td className="text-right text-subtle"><Money minor={f.projected_interest_minor} /></td></tr>)}</tbody></Table>
          )}
        </Card>
      </div>

      {p.closed_positions.length > 0 && (
        <Card title="Closed positions" className="mt-4">
          <Table><thead><tr><th>Instrument</th><th className="text-right">Invested</th><th className="text-right">Proceeds</th><th className="text-right">Realized gain</th></tr></thead>
            <tbody>{p.closed_positions.map((h: any) => <tr key={`${h.account_id}-${h.instrument_id}`}><td>{h.instrument_name}</td>
              <td className="text-right"><Money minor={h.invested_minor} /></td><td className="text-right"><Money minor={h.withdrawn_minor} /></td>
              <td className="text-right"><Money minor={h.realized_gain_minor} colored /></td></tr>)}</tbody></Table>
        </Card>
      )}

      <Card title="Investment transactions" className="mt-4">
        {!txns.data?.length ? <p className="text-sm text-subtle">None yet.</p> : (
          <Table><thead><tr><th>Date</th><th>Instrument</th><th>Type</th><th className="text-right">Qty</th><th className="text-right">Price</th><th className="text-right">Amount</th><th className="text-right">Charges</th><th>Account</th></tr></thead>
            <tbody>{txns.data.map((t) => <tr key={t.id}><td>{fmtDate(t.transaction_date)}</td><td>{t.instrument_name ?? "—"}</td><td>{t.transaction_type}{t.split_ratio && ` ×${t.split_ratio}`}</td>
              <td className="num text-right">{t.quantity ?? ""}</td><td className="num text-right">{t.unit_price ?? ""}</td><td className="text-right"><Money minor={t.gross_amount_minor} /></td>
              <td className="text-right"><Money minor={t.charges_minor} /></td><td className="text-xs">{acctName(t.account_id)}</td></tr>)}</tbody></Table>
        )}
      </Card>

      {modal === "instrument" && <InstrumentModal onClose={() => setModal(null)} />}
      {modal === "txn" && <InvTxnModal onClose={() => setModal(null)} />}
      {modal === "valuation" && <ValuationModal onClose={() => setModal(null)} />}
      {modal === "import" && <ImportModal onClose={() => setModal(null)} />}
      {modal === "fd" && <FDModal onClose={() => setModal(null)} />}
    </>
  );
}

function useInstruments() {
  return useQuery({ queryKey: ["instruments"], queryFn: () => api.get<any[]>("/investments/instruments") });
}

function InstrumentModal({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ name: "", instrument_type: "mutual_fund", identifier: "", issuer: "" });
  const save = useMut(() => api.post("/investments/instruments", f), onClose);
  return (
    <Modal open onClose={onClose} title="New instrument" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="grid gap-3">
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Type"><Select value={f.instrument_type} onChange={(e) => setF({ ...f, instrument_type: e.target.value })}>{INST_TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
        <Field label="ISIN / scheme code / symbol" hint="Unique identifier used to match imports"><Input value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} /></Field>
        <Field label="Issuer / AMC"><Input value={f.issuer} onChange={(e) => setF({ ...f, issuer: e.target.value })} /></Field>
        <ErrorBox error={save.error} />
      </div>
    </Modal>
  );
}

function InvTxnModal({ onClose }: { onClose: () => void }) {
  const accounts = useAccounts();
  const inst = useInstruments();
  const [f, setF] = useState({ account_id: "", instrument_id: "", transaction_date: todayIso(), transaction_type: "buy", quantity: "", unit_price: "", amount: "", charges: "", split_ratio: "", source_transaction_id: "" });
  const save = useMut(() => {
    const amount = f.amount ? parseRupees(f.amount) : 0;
    const charges = f.charges ? parseRupees(f.charges) : 0;
    if (amount === null || charges === null) throw new Error("Amounts must be numbers");
    return api.post("/investments/transactions", {
      account_id: Number(f.account_id), instrument_id: f.instrument_id ? Number(f.instrument_id) : null, transaction_date: f.transaction_date,
      transaction_type: f.transaction_type, quantity: f.quantity || null, unit_price: f.unit_price || null, gross_amount_minor: Math.abs(amount),
      charges_minor: Math.abs(charges), split_ratio: f.split_ratio || null, source_transaction_id: f.source_transaction_id ? Number(f.source_transaction_id) : null,
    });
  }, onClose);
  const s = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title="Investment transaction" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Account"><Select value={f.account_id} onChange={s("account_id")}><option value="">Choose…</option>
          {accounts.data?.filter((a) => ["brokerage", "mutual_fund", "investment_other", "fixed_deposit"].includes(a.account_type)).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label="Instrument"><Select value={f.instrument_id} onChange={s("instrument_id")}><option value="">—</option>{inst.data?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</Select></Field>
        <Field label="Date"><Input type="date" value={f.transaction_date} onChange={s("transaction_date")} /></Field>
        <Field label="Type"><Select value={f.transaction_type} onChange={s("transaction_type")}>{INV_TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
        <Field label="Quantity / units"><Input inputMode="decimal" value={f.quantity} onChange={s("quantity")} /></Field>
        <Field label="Unit price (₹)"><Input inputMode="decimal" value={f.unit_price} onChange={s("unit_price")} /></Field>
        <Field label="Gross amount (₹)" hint="Trade value, dividend or interest amount"><Input inputMode="decimal" value={f.amount} onChange={s("amount")} /></Field>
        <Field label="Charges (₹)"><Input inputMode="decimal" value={f.charges} onChange={s("charges")} /></Field>
        {f.transaction_type === "split" && <Field label="Split ratio" hint="New units per old unit, e.g. 2 for 1:2"><Input value={f.split_ratio} onChange={s("split_ratio")} /></Field>}
        <Field label="Linked bank transaction id (optional)" hint="Marks that bank debit as an investment purchase, not spending"><Input value={f.source_transaction_id} onChange={s("source_transaction_id")} /></Field>
      </div>
      <div className="mt-3"><ErrorBox error={save.error} /></div>
    </Modal>
  );
}

function ValuationModal({ onClose }: { onClose: () => void }) {
  const inst = useInstruments();
  const [f, setF] = useState({ instrument_id: "", valuation_date: todayIso(), unit_price: "", notes: "" });
  const save = useMut(() => api.post("/investments/valuations", { instrument_id: Number(f.instrument_id), valuation_date: f.valuation_date, unit_price: f.unit_price, source: "manual", notes: f.notes }), onClose);
  return (
    <Modal open onClose={onClose} title="Manual valuation" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="grid gap-3">
        <Field label="Instrument"><Select value={f.instrument_id} onChange={(e) => setF({ ...f, instrument_id: e.target.value })}><option value="">Choose…</option>{inst.data?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</Select></Field>
        <Field label="Valuation date"><Input type="date" value={f.valuation_date} onChange={(e) => setF({ ...f, valuation_date: e.target.value })} /></Field>
        <Field label="Unit price / NAV (₹)"><Input inputMode="decimal" value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value })} /></Field>
        <Field label="Source note (required)" hint="Where this price came from, e.g. 'AMC website NAV'"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <ErrorBox error={save.error} />
      </div>
    </Modal>
  );
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const accounts = useAccounts();
  const [file, setFile] = useState<File | null>(null);
  const [account, setAccount] = useState("");
  const [kind, setKind] = useState("transactions");
  const [preview, setPreview] = useState<any>(null);
  const run = useMut((dry: boolean) => {
    const fd = new FormData();
    fd.append("file", file!);
    fd.append("account_id", account);
    fd.append("kind", kind);
    fd.append("dry_run", String(dry));
    return api.post<any>("/investments/import", fd);
  }, (r) => (r.dry_run ? setPreview(r) : onClose()));
  return (
    <Modal open wide onClose={onClose} title="Import investment data" footer={<><Button onClick={onClose}>Cancel</Button>
      <Button disabled={!file || !account} loading={run.isPending} onClick={() => run.mutate(true)}>Preview</Button>
      <Button variant="primary" disabled={!preview || !preview.row_count} loading={run.isPending} onClick={() => run.mutate(false)}>Import {preview?.row_count ?? 0} row(s)</Button></>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="File (CSV/XLSX)"><Input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} /></Field>
        <Field label="Account"><Select value={account} onChange={(e) => setAccount(e.target.value)}><option value="">Choose…</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label="Contents"><Select value={kind} onChange={(e) => { setKind(e.target.value); setPreview(null); }}>
          <option value="transactions">Transactions (date, ISIN/name, type, units, price, amount)</option>
          <option value="valuations">NAVs / prices (date, ISIN/name, NAV or value)</option></Select></Field>
      </div>
      <ErrorBox error={run.error} />
      {preview && <div className="mt-3 space-y-2 text-sm">
        <p>Columns detected: {Object.entries(preview.columns).map(([k, v]) => `${k} ← "${v}"`).join(", ")}</p>
        {preview.errors.length > 0 && <Notice tone="bad">{preview.errors.length} row(s) cannot be imported: {preview.errors.slice(0, 5).map((e: any) => `row ${e.row}: ${e.error}`).join("; ")}</Notice>}
        <Table><thead><tr>{Object.keys(preview.rows[0] ?? {}).map((k) => <th key={k}>{k}</th>)}</tr></thead>
          <tbody>{preview.rows.slice(0, 50).map((r: any) => <tr key={r.row}>{Object.values(r).map((v: any, i) => <td key={i} className="text-xs">{String(v ?? "")}</td>)}</tr>)}</tbody></Table>
      </div>}
    </Modal>
  );
}

function FDModal({ onClose }: { onClose: () => void }) {
  const accounts = useAccounts();
  const [f, setF] = useState({ account_id: "", principal: "", opening_date: todayIso(), maturity_date: "", interest_rate: "", maturity_value: "" });
  const save = useMut(() => {
    const principal = parseRupees(f.principal);
    const mv = f.maturity_value ? parseRupees(f.maturity_value) : null;
    if (!principal) throw new Error("Principal is required");
    return api.post("/investments/fixed-deposits", { account_id: Number(f.account_id), principal_minor: principal, opening_date: f.opening_date,
      maturity_date: f.maturity_date || null, interest_rate: f.interest_rate || null, reported_maturity_value_minor: mv });
  }, onClose);
  const s = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title="Fixed deposit details" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="FD account" hint="Create an account of type Fixed deposit first"><Select value={f.account_id} onChange={s("account_id")}><option value="">Choose…</option>
          {accounts.data?.filter((a) => a.account_type === "fixed_deposit").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label="Principal (₹)"><Input value={f.principal} onChange={s("principal")} /></Field>
        <Field label="Opening date"><Input type="date" value={f.opening_date} onChange={s("opening_date")} /></Field>
        <Field label="Maturity date"><Input type="date" value={f.maturity_date} onChange={s("maturity_date")} /></Field>
        <Field label="Interest rate (% p.a.)"><Input value={f.interest_rate} onChange={s("interest_rate")} /></Field>
        <Field label="Bank-reported maturity value (₹)"><Input value={f.maturity_value} onChange={s("maturity_value")} /></Field>
      </div>
      <div className="mt-3"><ErrorBox error={save.error} /></div>
    </Modal>
  );
}
