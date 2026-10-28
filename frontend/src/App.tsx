import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeftRight, BarChart3, FileUp, GitCompareArrows, LayoutDashboard, LineChart, LogOut, Moon, PiggyBank,
  Receipt, Settings as SettingsIcon, Sun, Wallet,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { Button, Spinner } from "./components/ui";
import { api } from "./lib/api";
import AccountDetail from "./pages/AccountDetail";
import Accounts from "./pages/Accounts";
import Budgets from "./pages/Budgets";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/Import";
import Investments from "./pages/Investments";
import Login from "./pages/Login";
import Reconciliation from "./pages/Reconciliation";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import SpendingIncome from "./pages/SpendingIncome";
import Transactions from "./pages/Transactions";

interface AuthStatus { auth_enabled: boolean; setup_required: boolean; authenticated: boolean; username: string | null }

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/accounts", label: "Accounts", icon: Wallet },
  { to: "/transactions", label: "Transactions", icon: Receipt },
  { to: "/import", label: "Import Statements", icon: FileUp },
  { to: "/reconciliation", label: "Reconciliation", icon: GitCompareArrows },
  { to: "/spending", label: "Spending & Income", icon: ArrowLeftRight },
  { to: "/investments", label: "Investments", icon: LineChart },
  { to: "/budgets", label: "Budgets", icon: PiggyBank },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function ThemeToggle() {
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("ft-theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  return (
    <Button variant="ghost" size="sm" onClick={() => setDark(!dark)} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export default function App() {
  const qc = useQueryClient();
  const auth = useQuery({ queryKey: ["auth"], queryFn: () => api.get<AuthStatus>("/auth/status"), staleTime: 60_000 });
  useEffect(() => {
    const h = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener("ft:unauthorized", h);
    return () => window.removeEventListener("ft:unauthorized", h);
  }, [qc]);

  if (auth.isLoading) return <Spinner />;
  if (auth.isError) {
    return <div className="p-8 text-sm">Cannot reach the backend API. Is it running? ({String(auth.error)})</div>;
  }
  const a = auth.data!;
  if (a.auth_enabled && !a.authenticated) return <Login setup={a.setup_required} />;

  const logout = async () => {
    await api.post("/auth/logout");
    qc.clear();
    qc.invalidateQueries({ queryKey: ["auth"] });
  };

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-lg font-bold text-white">₹</div>
          <div>
            <p className="text-sm font-semibold leading-tight">Finance Tracker</p>
            <p className="text-xs text-subtle">Private · self-hosted</p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => clsx("focus-ring flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
                isActive ? "bg-primary/10 font-medium text-primary" : "text-subtle hover:bg-muted hover:text-fg")}>
              <Icon className="h-4 w-4" aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-border px-3 py-2">
          <span className="truncate text-xs text-subtle">{a.username ?? "Local mode"}</span>
          <div className="flex">
            <ThemeToggle />
            {a.auth_enabled && <Button variant="ghost" size="sm" onClick={logout} aria-label="Sign out"><LogOut className="h-4 w-4" /></Button>}
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <nav className="no-print flex gap-1 overflow-x-auto border-b border-border bg-surface px-2 py-2 md:hidden" aria-label="Main mobile">
          {NAV.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => clsx("whitespace-nowrap rounded px-2 py-1 text-xs",
              isActive ? "bg-primary/10 text-primary" : "text-subtle")}>{label}</NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 md:p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/accounts/:id" element={<AccountDetail />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/import/:batchId" element={<ImportPage />} />
            <Route path="/reconciliation" element={<Reconciliation />} />
            <Route path="/spending" element={<SpendingIncome />} />
            <Route path="/investments" element={<Investments />} />
            <Route path="/budgets" element={<Budgets />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<p className="text-sm">Page not found.</p>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
