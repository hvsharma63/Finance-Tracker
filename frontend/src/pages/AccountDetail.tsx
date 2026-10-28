import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AccountForm } from "@/components/AccountForm";
import { Button, Card, Confirm, ErrorBox, Money, Notice, PageHeader, Spinner, Stat, Status, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { ACCOUNT_TYPE_LABELS, fmtDate, fmtDateTime } from "@/lib/format";
import { useMut } from "@/lib/hooks";
import type { Account, Batch, Paged } from "@/lib/types";

export default function AccountDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["account", id], queryFn: () => api.get<Account>(`/accounts/${id}`) });
  const batches = useQuery({ queryKey: ["imports", "account", id], queryFn: () => api.get<Paged<Batch>>("/imports", { account_id: id }) });
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const remove = useMut(() => api.del(`/accounts/${id}`), () => nav("/accounts"));
  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const a = q.data!;
  const owed = a.is_liability;
  const show = (m: number | null) => (owed && m != null ? -m : m);

  return (
    <>
      <PageHeader title={a.name} description={`${ACCOUNT_TYPE_LABELS[a.account_type]}${a.institution ? " · " + a.institution : ""}${a.masked_identifier ? " · " + a.masked_identifier : ""}`}
        actions={<>
          <Button onClick={() => nav(`/transactions?account_id=${a.id}`)}>Transactions</Button>
          <Button onClick={() => nav(`/import?account=${a.id}`)}>Import statement</Button>
          <Button onClick={() => setEdit(true)}>Edit</Button>
          <Button variant="ghost" onClick={() => setDel(true)}>Delete</Button>
        </>} />

      {a.balance_status === "estimated" && <div className="mb-3"><Notice>Opening balance unknown, so the calculated balance cannot be shown. Import a statement with an opening balance or set it via Edit.</Notice></div>}
      {a.opening_verification === "unverified" && a.opening_balance_minor != null && <div className="mb-3"><Notice tone="info">
        Opening balance {a.opening_source === "statement" ? "was taken from the earliest imported statement" : "was entered manually"} and is not yet verified. Edit the account to mark it verified once checked.</Notice></div>}
      {(a.coverage_gaps?.length ?? 0) > 0 && <div className="mb-3"><Notice>Statement coverage gaps: {a.coverage_gaps!.map((g) => `${fmtDate(g.from)} → ${fmtDate(g.to)}`).join(", ")}. Transactions in gaps are missing from the balance.</Notice></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={owed ? "Calculated amount owed" : "Calculated balance"} value={<Money minor={show(a.calculated_balance_minor)} />}
          sub={<>Opening {owed ? "owed " : ""}<Money minor={show(a.opening_balance_minor)} /> on {fmtDate(a.opening_date)} + movements</>} />
        <Stat label="Last statement-reported balance" value={<Money minor={show(a.last_statement_balance_minor)} />} sub={`Statement ending ${fmtDate(a.last_statement_date)}`} />
        <Stat label="Coverage" value={a.coverage_end ? fmtDate(a.coverage_end) : "None"} sub={a.coverage_start ? `From ${fmtDate(a.coverage_start)} · ${a.statement_count} statement(s)` : "No statements imported"} />
        <Stat label="Status" value={<div className="flex flex-wrap gap-1"><Status status={a.balance_status} /><Status status={a.reconciliation_status} /></div>}
          sub={`Last import ${fmtDateTime(a.last_import_at)}`} />
      </div>

      <Card title="Statements" className="mt-4" subtitle="Opening + signed movements must equal the reported closing balance">
        {a.statements?.length ? (
          <Table>
            <thead><tr><th>Period</th><th className="text-right">Reported opening</th><th className="text-right">Reported closing</th><th className="text-right">Calculated closing</th><th className="text-right">Difference</th><th>Status</th><th /></tr></thead>
            <tbody>{a.statements.map((s) => (
              <tr key={s.id}>
                <td>{fmtDate(s.start_date)} – {fmtDate(s.end_date)}</td>
                <td className="text-right"><Money minor={s.reported_opening_minor} /></td>
                <td className="text-right"><Money minor={s.reported_closing_minor} /></td>
                <td className="text-right"><Money minor={s.calculated_closing_minor} /></td>
                <td className="text-right">{s.discrepancy_minor ? <Money minor={s.discrepancy_minor} className="font-semibold text-negative" /> : "—"}</td>
                <td><Status status={s.reconciliation_status} /></td>
                <td><Link className="text-xs text-primary hover:underline" to={`/import/${s.import_batch_id}`}>Import</Link></td>
              </tr>))}
            </tbody>
          </Table>
        ) : <p className="text-sm text-subtle">No statements imported for this account yet.</p>}
      </Card>

      <Card title="Import history" className="mt-4">
        {batches.data?.items.length ? (
          <Table>
            <thead><tr><th>#</th><th>File</th><th>Parser</th><th>Status</th><th className="text-right">Rows</th><th>Imported</th></tr></thead>
            <tbody>{batches.data.items.map((b) => (
              <tr key={b.id}><td><Link className="text-primary hover:underline" to={`/import/${b.id}`}>{b.id}</Link></td><td>{b.filename}</td>
                <td className="text-xs">{b.parser_name} {b.parser_version}</td><td><Status status={b.status} /></td>
                <td className="num text-right">{b.row_counts.accepted ?? b.row_counts.to_import ?? 0}/{b.row_counts.extracted ?? 0}</td>
                <td>{fmtDateTime(b.committed_at ?? b.created_at)}</td></tr>))}
            </tbody>
          </Table>
        ) : <p className="text-sm text-subtle">No imports.</p>}
      </Card>

      {edit && <AccountForm open account={a} onClose={() => setEdit(false)} />}
      <Confirm open={del} title="Delete account" danger confirmLabel="Delete account" loading={remove.isPending}
        onCancel={() => setDel(false)} onConfirm={() => remove.mutate(undefined)}>
        <p>Only accounts without transactions or imports can be deleted. For accounts with history, set them to inactive instead.</p>
        <ErrorBox error={remove.error} />
      </Confirm>
    </>
  );
}
