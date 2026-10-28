import { useState } from "react";
import { api } from "@/lib/api";
import { ACCOUNT_TYPE_LABELS, minorToInput, parseRupees } from "@/lib/format";
import { useMut } from "@/lib/hooks";
import type { Account } from "@/lib/types";
import { Button, ErrorBox, Field, Input, Modal, Select } from "./ui";

export function AccountForm({ open, onClose, account }: { open: boolean; onClose: () => void; account?: Account }) {
  const [f, setF] = useState({
    name: account?.name ?? "", institution: account?.institution ?? "", account_type: account?.account_type ?? "savings",
    masked_identifier: account?.masked_identifier ?? "", opening: minorToInput(account?.opening_balance_minor),
    opening_date: account?.opening_date ?? "", opening_verification: account?.opening_verification ?? "unverified",
    notes: account?.notes ?? "", is_active: account?.is_active ?? true,
  });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));
  const isLiability = ["credit_card", "loan", "liability_other"].includes(f.account_type);

  const save = useMut(async () => {
    const body: Record<string, unknown> = {
      name: f.name.trim(), institution: f.institution || null, masked_identifier: f.masked_identifier || null,
      notes: f.notes || null, is_active: f.is_active,
    };
    if (f.opening.trim()) {
      const v = parseRupees(f.opening);
      if (v === null) throw new Error("Opening balance must be a number like 12500.00");
      // Liabilities are entered as amount owed and stored negative (holder perspective).
      body.opening_balance_minor = isLiability ? -Math.abs(v) : v;
      body.opening_date = f.opening_date || null;
      body.opening_verification = f.opening_verification;
    }
    if (account) {
      if (!f.opening.trim() && account.opening_balance_minor !== null) body.clear_opening_balance = true;
      return api.patch(`/accounts/${account.id}`, body);
    }
    return api.post("/accounts", { ...body, account_type: f.account_type });
  }, onClose);

  return (
    <Modal open={open} onClose={onClose} title={account ? `Edit ${account.name}` : "New account"} footer={<>
      <Button onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={save.isPending} onClick={() => { setErr(null); save.mutate(undefined, { onError: (e) => setErr(e.message) }); }}>Save</Button>
    </>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Account name"><Input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. HDFC Savings" /></Field>
        <Field label="Institution"><Input value={f.institution} onChange={(e) => set("institution", e.target.value)} /></Field>
        <Field label="Type" hint={account ? "Type cannot change after creation" : undefined}>
          <Select value={f.account_type} disabled={!!account} onChange={(e) => set("account_type", e.target.value)}>
            {Object.entries(ACCOUNT_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        <Field label="Last 4 digits (optional)" hint="Only the last 4 digits are stored. Used to suggest the account on import.">
          <Input value={f.masked_identifier} onChange={(e) => set("masked_identifier", e.target.value)} placeholder="XX1234" />
        </Field>
        <Field label={isLiability ? "Opening amount owed (₹)" : "Opening balance (₹)"} hint="Leave empty if unknown — it can be taken from the first statement.">
          <Input inputMode="decimal" value={f.opening} onChange={(e) => set("opening", e.target.value)} />
        </Field>
        <Field label="Opening balance date"><Input type="date" value={f.opening_date} onChange={(e) => set("opening_date", e.target.value)} /></Field>
        <Field label="Opening balance status">
          <Select value={f.opening_verification} onChange={(e) => set("opening_verification", e.target.value)}>
            <option value="unverified">Unverified</option><option value="verified">Verified against a statement</option>
          </Select>
        </Field>
        <Field label="Status">
          <Select value={f.is_active ? "1" : "0"} onChange={(e) => set("is_active", e.target.value === "1")}>
            <option value="1">Active</option><option value="0">Inactive (closed)</option>
          </Select>
        </Field>
        <div className="sm:col-span-2"><Field label="Notes"><Input value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field></div>
      </div>
      <div className="mt-3"><ErrorBox error={err} /></div>
    </Modal>
  );
}
