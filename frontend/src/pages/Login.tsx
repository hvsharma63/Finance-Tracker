import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function Login({ setup }: { setup: boolean }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (setup && password !== confirm) return setError(new Error("Passwords do not match"));
    setBusy(true);
    try {
      await api.post(setup ? "/auth/setup" : "/auth/login", { username, password });
      await qc.invalidateQueries();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-surface p-6">
        <div>
          <h1 className="text-lg font-semibold">{setup ? "Create your account" : "Sign in"}</h1>
          <p className="mt-1 text-sm text-subtle">
            {setup ? "First run: choose a username and a password of at least 10 characters. Your data never leaves this machine."
              : "Finance Tracker — private, self-hosted."}
          </p>
        </div>
        <Field label="Username"><Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Field>
        <Field label="Password">
          <Input type="password" autoComplete={setup ? "new-password" : "current-password"} value={password}
            onChange={(e) => setPassword(e.target.value)} required minLength={setup ? 10 : 1} />
        </Field>
        {setup && <Field label="Confirm password"><Input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></Field>}
        <ErrorBox error={error} />
        <Button type="submit" variant="primary" className="w-full" loading={busy}>{setup ? "Create account" : "Sign in"}</Button>
      </form>
    </div>
  );
}
