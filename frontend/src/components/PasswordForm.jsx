import { useState } from "react";
import { useAuth } from "../lib/auth";
import { Button, Field, Input, useToast } from "./ui";

/** Change your own password (used in Settings, the user menu and the forced first-login change). */
export default function PasswordForm({ onDone, submitLabel = "Update password" }) {
  const { changePassword } = useAuth();
  const toast = useToast();
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mismatch = pw.confirm && pw.next !== pw.confirm;

  const submit = async (e) => {
    e.preventDefault();
    if (pw.next !== pw.confirm) return setError("The new passwords do not match");
    setBusy(true);
    setError("");
    try {
      await changePassword(pw.current, pw.next);
      toast("Password changed. Other sessions were signed out.", "success");
      setPw({ current: "", next: "", confirm: "" });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      {error && <p role="alert" className="rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{error}</p>}
      <Field label="Current password">
        <Input type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" required />
      </Field>
      <Field label="New password" hint="At least 8 characters, with upper-case and lower-case letters and a digit">
        <Input type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" required />
      </Field>
      <Field label="Repeat new password" hint={mismatch ? "Does not match" : undefined}>
        <Input type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} autoComplete="new-password" required />
      </Field>
      <Button type="submit" loading={busy} disabled={!pw.current || !pw.next || !pw.confirm || mismatch}>{submitLabel}</Button>
    </form>
  );
}
