/** Chart building blocks. Colours come from validated CSS series tokens (light/dark stepped separately). */
import type { ReactNode } from "react";
import { inr, fmtMonth } from "@/lib/format";

export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
export const GRID = "var(--grid)";
export const AXIS = "var(--axis)";

export const axisProps = {
  stroke: AXIS,
  tick: { fill: AXIS, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: GRID },
};

export function compactInr(minor: number) {
  const r = Math.abs(minor) / 100;
  const sign = minor < 0 ? "-" : "";
  if (r >= 1e7) return `${sign}₹${(r / 1e7).toFixed(1)}Cr`;
  if (r >= 1e5) return `${sign}₹${(r / 1e5).toFixed(1)}L`;
  if (r >= 1e3) return `${sign}₹${(r / 1e3).toFixed(0)}k`;
  return `${sign}₹${r.toFixed(0)}`;
}

interface TipPayload { name?: string; value?: number; color?: string; dataKey?: string | number; payload?: Record<string, unknown> }

export function MoneyTooltip({ active, payload, label, labelFormat = fmtMonth }: {
  active?: boolean; payload?: TipPayload[]; label?: string; labelFormat?: (l: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-md">
      {label && <p className="mb-1 font-semibold">{labelFormat(String(label))}</p>}
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-subtle">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden />{p.name}
          </span>
          <span className="num font-medium text-fg">{p.value == null ? "unknown" : inr(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-subtle" aria-hidden>
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}

/** Accessible table alternative for every chart. */
export function ChartTable({ caption, columns, rows }: { caption: string; columns: string[]; rows: ReactNode[][] }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-subtle hover:text-fg">Show as table</summary>
      <table className="mt-2 w-full text-left">
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map((c) => <th key={c} className="border-b border-border py-1 pr-3 font-semibold">{c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="num border-b border-border py-1 pr-3">{c}</td>)}</tr>)}</tbody>
      </table>
    </details>
  );
}
