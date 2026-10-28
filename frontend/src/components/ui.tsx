import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import {
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, cloneElement,
  isValidElement, useEffect, useId, useRef,
} from "react";
import { inr } from "@/lib/format";

export function Button({
  variant = "secondary", size = "md", className, loading, children, ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean;
}) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={clsx(
        "focus-ring inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-primary text-white hover:bg-primary/90",
        variant === "secondary" && "border border-border bg-surface hover:bg-muted",
        variant === "ghost" && "hover:bg-muted",
        variant === "danger" && "bg-negative text-white hover:bg-negative/90",
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className, subtitle }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; subtitle?: ReactNode;
}) {
  return (
    <section className={clsx("rounded-lg border border-border bg-surface", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-subtle">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Label + control. The label is linked by id so option text never leaks into the accessible name. */
export function Field({ label, hint, children, error }: { label: string; hint?: ReactNode; children: ReactNode; error?: string }) {
  const autoId = useId();
  const hintId = `${autoId}-hint`;
  const child = isValidElement<{ id?: string; "aria-label"?: string; "aria-describedby"?: string }>(children) ? children : null;
  const id = child?.props.id ?? autoId;
  const control = child
    ? cloneElement(child, { id, "aria-label": undefined, "aria-describedby": hint || error ? hintId : undefined })
    : children;
  return (
    <div className="block text-sm">
      <label htmlFor={id} className="mb-1 block font-medium">{label}</label>
      {control}
      {hint && !error && <span id={hintId} className="mt-1 block text-xs text-subtle">{hint}</span>}
      {error && <span id={hintId} className="mt-1 block text-xs text-negative">{error}</span>}
    </div>
  );
}

const inputCls = "focus-ring h-9 w-full rounded-md border border-border bg-surface px-2.5 text-sm placeholder:text-subtle/70";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx(inputCls, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={clsx(inputCls, "pr-7", props.className)} />;
}

export function Badge({ tone = "neutral", children, title }: {
  tone?: "neutral" | "good" | "warn" | "bad" | "info"; children: ReactNode; title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium",
        tone === "neutral" && "bg-muted text-subtle",
        tone === "good" && "bg-positive/10 text-positive",
        tone === "warn" && "bg-warning/15 text-warning",
        tone === "bad" && "bg-negative/10 text-negative",
        tone === "info" && "bg-primary/10 text-primary",
      )}
    >
      {children}
    </span>
  );
}

/** Status pill that never relies on colour alone: icon + text. */
export function Status({ status }: { status: string }) {
  const map: Record<string, [string, "good" | "warn" | "bad" | "neutral" | "info", typeof CheckCircle2]> = {
    reconciled: ["Reconciled", "good", CheckCircle2],
    passed: ["Passed", "good", CheckCircle2],
    verified: ["Verified", "good", CheckCircle2],
    committed: ["Imported", "good", CheckCircle2],
    approved: ["Approved", "good", CheckCircle2],
    discrepancy: ["Discrepancy", "bad", XCircle],
    failed: ["Failed", "bad", XCircle],
    rejected: ["Rejected", "neutral", XCircle],
    unverifiable: ["Unverifiable", "neutral", Info],
    unavailable: ["Unavailable", "neutral", Info],
    no_statements: ["No statements", "neutral", Info],
    unverified: ["Unverified", "warn", AlertTriangle],
    estimated: ["Estimated", "warn", AlertTriangle],
    preview: ["Preview", "info", Info],
    suggested: ["Suggested", "info", Info],
    undone: ["Undone", "neutral", Info],
    discarded: ["Discarded", "neutral", Info],
    deleted: ["Deleted", "neutral", Info],
  };
  const [label, tone, Icon] = map[status] ?? [status, "neutral", Info];
  return <Badge tone={tone}><Icon className="h-3 w-3" aria-hidden />{label}</Badge>;
}

export function Money({ minor, className, sign, colored }: { minor: number | null | undefined; className?: string; sign?: boolean; colored?: boolean }) {
  return (
    <span className={clsx("num whitespace-nowrap", colored && minor != null && (minor < 0 ? "text-negative" : minor > 0 ? "text-positive" : ""), className)}>
      {inr(minor, { sign })}
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-subtle" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-negative/30 bg-negative/5 p-3 text-sm text-negative">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> <span>{msg}</span>
    </div>
  );
}

export function Notice({ tone = "warn", children }: { tone?: "warn" | "info" | "bad" | "good"; children: ReactNode }) {
  const Icon = tone === "good" ? CheckCircle2 : tone === "info" ? Info : tone === "bad" ? XCircle : AlertTriangle;
  return (
    <div className={clsx("flex items-start gap-2 rounded-md border p-3 text-sm",
      tone === "warn" && "border-warning/30 bg-warning/10",
      tone === "info" && "border-primary/25 bg-primary/5",
      tone === "bad" && "border-negative/30 bg-negative/5",
      tone === "good" && "border-positive/30 bg-positive/5")}>
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", tone === "warn" && "text-warning", tone === "info" && "text-primary",
        tone === "bad" && "text-negative", tone === "good" && "text-positive")} aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-subtle">{children}</div>}
      {action}
    </div>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm [&_td]:border-b [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_th]:border-b [&_th]:border-border [&_th]:bg-muted/60 [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-xs [&_th]:font-semibold [&_th]:text-subtle">
        {children}
      </table>
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    el?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && el) {
        const f = Array.from(el.querySelectorAll<HTMLElement>("button,input,select,textarea,a[href],[tabindex]:not([tabindex='-1'])"))
          .filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={clsx("w-full rounded-lg border border-border bg-surface shadow-xl", wide ? "max-w-4xl" : "max-w-lg")}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button data-close onClick={onClose} className="focus-ring rounded p-1 hover:bg-muted" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ open, title, children, confirmLabel = "Confirm", danger, onConfirm, onCancel, loading }: {
  open: boolean; title: string; children: ReactNode; confirmLabel?: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void; loading?: boolean;
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title} footer={<>
      <Button onClick={onCancel}>Cancel</Button>
      <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>{confirmLabel}</Button>
    </>}>
      <div className="space-y-2 text-sm">{children}</div>
    </Modal>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-sm text-subtle">
      <span>{total.toLocaleString("en-IN")} result{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>Previous</Button>
        <span className="num">Page {page} of {pages}</span>
        <Button size="sm" onClick={() => onPage(page + 1)} disabled={page >= pages}>Next</Button>
      </div>
    </div>
  );
}

export function Stat({ label, value, sub, warn }: { label: string; value: ReactNode; sub?: ReactNode; warn?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-medium text-subtle">{label}</p>
      <p className="num mt-1 text-xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs text-subtle">{sub}</p>}
      {warn && <p className="mt-1 flex items-start gap-1 text-xs text-warning"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{warn}</p>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-subtle">{description}</p>}
      </div>
      {actions && <div className="no-print flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
