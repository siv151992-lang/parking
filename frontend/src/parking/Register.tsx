// Employee self-registration (only when an administrator allowed the company's email domains).
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { get } from "../lib/api";
import { useAuthT } from "./auth";
import { Button } from "./ui";

const input = "block w-full rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600";

export default function Register() {
  const { register } = useAuthT();
  const nav = useNavigate();
  const [info, setInfo] = useState<{ enabled: boolean; domains: string[] } | null>(null);
  const [f, setF] = useState({ full_name: "", email: "", password: "", confirm: "", phone: "", department: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get("/api/auth/signup-info").then(setInfo).catch(() => setInfo({ enabled: false, domains: [] }));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (f.password !== f.confirm) return setError("The passwords do not match");
    setBusy(true);
    setError("");
    try {
      await register({ full_name: f.full_name, email: f.email, password: f.password, phone: f.phone, department: f.department });
      nav("/park/vehicles");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200 p-6 sm:p-8 space-y-5">
        <div>
          <h1 className="text-2xl font-bold text-navy-900">Create your parking account</h1>
          <p className="text-sm text-slate-500 mt-1">For employees: book office parking for yourself and your visitors.</p>
        </div>
        {info === null ? <p className="text-sm text-slate-500">Loading…</p> : !info.enabled ? (
          <p className="text-sm text-slate-700 bg-slate-50 rounded-lg p-3">
            Self-registration is not switched on. Ask your parking administrator for an account.
          </p>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            {error && <p role="alert" className="rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{error}</p>}
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Full name</span>
              <input className={input} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required minLength={2} autoComplete="name" /></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Company email ({info.domains.map((d) => `@${d}`).join(", ")})</span>
              <input className={input} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoComplete="email" /></label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Phone (optional)</span>
                <input className={input} type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} autoComplete="tel" /></label>
              <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Department (optional)</span>
                <input className={input} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} /></label>
            </div>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Password</span>
              <input className={input} type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required autoComplete="new-password" />
              <span className="block text-[11px] text-slate-400 mt-1">At least 8 characters, with upper-case and lower-case letters and a digit</span></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Repeat password</span>
              <input className={input} type="password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} required autoComplete="new-password" /></label>
            <Button type="submit" loading={busy} className="w-full">Create account</Button>
          </form>
        )}
        <p className="text-sm text-slate-500">Already have an account? <Link to="/login" className="font-semibold text-navy-700 hover:underline">Sign in</Link></p>
      </div>
    </div>
  );
}
