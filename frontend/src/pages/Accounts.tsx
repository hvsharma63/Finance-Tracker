import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { AccountForm } from "@/components/AccountForm";
import { Button, Empty, ErrorBox, Money, PageHeader, Spinner, Status, Table } from "@/components/ui";
import { ACCOUNT_TYPE_LABELS, fmtDate } from "@/lib/format";
import { useAccounts } from "@/lib/hooks";

export default function Accounts() {
  const q = useAccounts();
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHeader title="Accounts" description="Balances are calculated from the verified opening balance plus every imported movement."
        actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New account</Button>} />
      {q.isLoading ? <Spinner /> : q.isError ? <ErrorBox error={q.error} /> : q.data!.length === 0 ? (
        <Empty title="No accounts yet" action={<Button variant="primary" onClick={() => setOpen(true)}>Create your first account</Button>}>
          Add each bank account, credit card, loan and investment account you want to track. Full account numbers are never needed.
        </Empty>
      ) : (
        <Table>
          <thead><tr><th>Account</th><th>Type</th><th className="text-right">Calculated balance</th><th className="text-right">Last statement balance</th><th>Coverage to</th><th>Balance basis</th><th>Reconciliation</th></tr></thead>
          <tbody>
            {q.data!.map((a) => (
              <tr key={a.id} className={a.is_active ? "" : "opacity-60"}>
                <td><Link to={`/accounts/${a.id}`} className="font-medium text-primary hover:underline">{a.name}</Link>
                  <div className="text-xs text-subtle">{a.institution} {a.masked_identifier}</div></td>
                <td>{ACCOUNT_TYPE_LABELS[a.account_type]}{!a.is_active && " (inactive)"}</td>
                <td className="text-right">{a.is_liability && a.calculated_balance_minor != null ? <span title="Amount owed"><Money minor={-a.calculated_balance_minor} /> owed</span> : <Money minor={a.calculated_balance_minor} />}</td>
                <td className="text-right"><Money minor={a.last_statement_balance_minor} /><div className="text-xs text-subtle">{fmtDate(a.last_statement_date)}</div></td>
                <td>{fmtDate(a.coverage_end)}</td>
                <td><Status status={a.balance_status} /></td>
                <td><Status status={a.reconciliation_status} /></td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {open && <AccountForm open onClose={() => setOpen(false)} />}
    </>
  );
}
