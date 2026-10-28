import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { Account, Category } from "./types";

export function useAccounts() {
  return useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
}

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: () => api.get<Category[]>("/categories"), staleTime: 60_000 });
}

/** Categories as "Parent › Child" options, active only, grouped by parent. */
export function categoryOptions(cats: Category[] | undefined) {
  if (!cats) return [];
  const parents = cats.filter((c) => c.parent_id === null);
  return parents.map((p) => ({
    group: p.name,
    options: [p, ...cats.filter((c) => c.parent_id === p.id && c.is_active)].map((c) => ({
      id: c.id, label: c.parent_id ? c.name : `${c.name} (general)`, type: c.reporting_type,
    })),
  }));
}

/** Invalidate everything derived from the ledger after a mutation. */
export function useLedgerInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function useMut<TVars, TRes = unknown>(fn: (v: TVars) => Promise<TRes>, onSuccess?: (r: TRes) => void) {
  const invalidate = useLedgerInvalidate();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      invalidate();
      onSuccess?.(r);
    },
  });
}
