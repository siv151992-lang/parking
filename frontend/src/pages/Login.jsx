import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Lock, User } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button, inputCls } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      nav("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex flex-col justify-between bg-navy-900 text-white p-12 relative overflow-hidden">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-white text-navy-900 flex items-center justify-center font-black text-2xl">P</div>
          <span className="text-xl font-bold">Smart Parking</span>
        </div>
        <div className="relative z-10">
          <h1 className="text-4xl font-bold leading-tight">Every vehicle, recognised and counted — in real time.</h1>
          <p className="text-slate-300 mt-4 max-w-md">
            Centralised ANPR camera monitoring, automatic entry/exit counting with duplicate prevention, live occupancy and reports.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Camera size={16} /> RTSP · ONVIF · YOLO · PaddleOCR
        </div>
        <div className="absolute -right-24 -bottom-24 w-96 h-96 rounded-full border-[40px] border-white/5" />
      </div>
      <div className="flex items-center justify-center p-6 bg-slate-50">
        <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-slate-200 p-8 space-y-5">
          <div>
            <h2 className="text-2xl font-bold text-navy-900">Sign in</h2>
            <p className="text-sm text-slate-500 mt-1">Parking management console</p>
          </div>
          {error && <div className="rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{error}</div>}
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Username</span>
            <div className="relative mt-1">
              <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input className={`${inputCls} pl-9`} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
            </div>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Password</span>
            <div className="relative mt-1">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input type="password" className={`${inputCls} pl-9`} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </div>
          </label>
          <Button type="submit" loading={busy} className="w-full">
            Sign in
          </Button>
          <p className="text-[11px] text-slate-400 text-center">Accounts are locked for 15 minutes after 5 failed attempts.</p>
        </form>
      </div>
    </div>
  );
}
