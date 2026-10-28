import { categoryOptions, useCategories } from "@/lib/hooks";
import { Select } from "./ui";

export function CategorySelect({ value, onChange, allowNone = true, noneLabel = "— Uncategorized —", id, ariaLabel }: {
  value: number | null | undefined; onChange: (id: number | null) => void; allowNone?: boolean; noneLabel?: string;
  id?: string; ariaLabel?: string;
}) {
  const cats = useCategories();
  return (
    <Select id={id} aria-label={id ? undefined : ariaLabel ?? "Category"} value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      {allowNone && <option value="">{noneLabel}</option>}
      {categoryOptions(cats.data).map((g) => (
        <optgroup key={g.group} label={g.group}>
          {g.options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </optgroup>
      ))}
    </Select>
  );
}
