import { useAccounts } from "@/lib/hooks";
import { daysAgoIso, monthStartIso, todayIso } from "@/lib/format";
import { Button, Input, Select } from "./ui";

export interface Range { start: string; end: string; account_id?: string }

function lastMonth(): Range {
  const d = new Date(monthStartIso());
  d.setDate(0);
  const end = d.toISOString().slice(0, 10);
  return { start: end.slice(0, 8) + "01", end };
}

function fyStart(): string {
  const t = todayIso();
  const y = Number(t.slice(0, 4));
  return Number(t.slice(5, 7)) >= 4 ? `${y}-04-01` : `${y - 1}-04-01`;
}

export function RangeFilter({ value, onChange, accounts = true }: { value: Range; onChange: (r: Range) => void; accounts?: boolean }) {
  const accts = useAccounts();
  const presets: [string, Range][] = [
    ["This month", { start: monthStartIso(), end: todayIso() }],
    ["Last month", lastMonth()],
    ["Last 90 days", { start: daysAgoIso(90), end: todayIso() }],
    ["This FY", { start: fyStart(), end: todayIso() }],
    ["Last 12 months", { start: daysAgoIso(365), end: todayIso() }],
  ];
  return (
    <div className="no-print mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface p-3">
      {presets.map(([l, r]) => (
        <Button key={l} size="sm" variant={value.start === r.start && value.end === r.end ? "primary" : "secondary"}
          onClick={() => onChange({ ...value, ...r })}>{l}</Button>
      ))}
      <Input type="date" aria-label="From" className="w-40" value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} />
      <span className="text-subtle">to</span>
      <Input type="date" aria-label="To" className="w-40" value={value.end} onChange={(e) => onChange({ ...value, end: e.target.value })} />
      {accounts && (
        <Select aria-label="Account" className="w-52" value={value.account_id ?? ""} onChange={(e) => onChange({ ...value, account_id: e.target.value || undefined })}>
          <option value="">All accounts</option>
          {accts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
      )}
    </div>
  );
}
