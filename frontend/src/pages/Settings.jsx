import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime } from "../lib/format";
import { Button, Card, Field, Input, PageHeader, Pagination, Spinner, Table, useFetch, useToast } from "../components/ui";

function SystemStatus() {
  const s = useFetch(() => get("/api/dashboard/system"), []);
  if (!s.data) return <Spinner />;
  const e = s.data.anpr_engine;
  return (
    <div className="grid sm:grid-cols-3 gap-3 text-sm">
      <div className="bg-slate-50 rounded-lg p-3">
        <p className="text-xs text-slate-500">ANPR engine (real cameras)</p>
        <p className="font-semibold">{e.loaded ? `Loaded · ${e.vehicle_model} + ${e.ocr}` : e.initialised ? "Unavailable" : "Not initialised (no real camera running)"}</p>
        {e.error && <p className="text-xs text-amber-700 mt-1">{e.error}</p>}
      </div>
      <div className="bg-slate-50 rounded-lg p-3"><p className="text-xs text-slate-500">Camera workers</p><p className="font-semibold">{Object.keys(s.data.workers).length} running</p></div>
      <div className="bg-slate-50 rounded-lg p-3"><p className="text-xs text-slate-500">WebSocket clients</p><p className="font-semibold">{s.data.websocket_clients}</p></div>
    </div>
  );
}

function AuditLog() {
  const [f, setF] = useState({ q: "", page: 1 });
  const data = useFetch(() => get("/api/audit-logs", { ...f, page_size: 20 }), [JSON.stringify(f)]);
  return (
    <Card title="Activity / audit log" bodyClass="p-0" action={<div className="w-56"><Input placeholder="Search user / action" value={f.q} onChange={(e) => setF({ q: e.target.value, page: 1 })} /></div>}>
      {!data.data ? <Spinner /> : (
        <>
          <Table rows={data.data.items} columns={[
            { key: "created_at", label: "Time", render: (r) => fmtDateTime(r.created_at) },
            { key: "username", label: "User" },
            { key: "action", label: "Action", render: (r) => <span className="font-mono text-xs">{r.action}</span> },
            { key: "entity", label: "Entity", render: (r) => <span className="text-xs">{r.entity_type}{r.entity_id ? ` #${r.entity_id}` : ""}</span> },
            { key: "details", label: "Details", render: (r) => <span className="text-xs text-slate-500 font-mono block max-w-md truncate" title={JSON.stringify(r.details)}>{JSON.stringify(r.details)}</span> },
            { key: "ip_address", label: "IP" },
          ]} />
          <Pagination page={f.page} pageSize={20} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
        </>
      )}
    </Card>
  );
}

export default function Settings() {
  const { can } = useAuth();
  const toast = useToast();
  const st = useFetch(() => get("/api/settings"), []);
  const [vals, setVals] = useState({});
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  useEffect(() => {
    if (st.data) setVals(Object.fromEntries(st.data.map((s) => [s.key, s.value])));
  }, [st.data]);

  const save = async () => {
    const changes = {};
    st.data.forEach((s) => {
      let v = vals[s.key];
      if (s.type === "int") v = parseInt(v, 10);
      if (s.type === "float") v = parseFloat(v);
      if (JSON.stringify(v) !== JSON.stringify(s.value)) changes[s.key] = v;
    });
    if (!Object.keys(changes).length) return toast("No changes", "info");
    try {
      await put("/api/settings", changes);
      toast("Settings saved", "success");
      st.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const changePw = async () => {
    try {
      await post("/api/auth/change-password", pw);
      toast("Password changed", "success");
      setPw({ current_password: "", new_password: "" });
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" subtitle="Detection, duplicate prevention, alerting and retention rules">
        {can("settings.manage") && <Button icon={Save} onClick={save}>Save settings</Button>}
      </PageHeader>
      <Card title="System status"><SystemStatus /></Card>
      <Card title="Processing rules">
        {!st.data ? <Spinner /> : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {st.data.map((s) => (
              <Field key={s.key} label={s.key.replaceAll("_", " ")} hint={`${s.description} (default: ${String(s.default)})`}>
                {s.type === "bool" ? (
                  <label className="flex items-center gap-2 text-sm py-2"><input type="checkbox" disabled={!can("settings.manage")} checked={!!vals[s.key]} onChange={(e) => setVals({ ...vals, [s.key]: e.target.checked })} /> Enabled</label>
                ) : (
                  <Input type={s.type === "str" ? "text" : "number"} disabled={!can("settings.manage")} value={vals[s.key] ?? ""} onChange={(e) => setVals({ ...vals, [s.key]: e.target.value })} />
                )}
              </Field>
            ))}
          </div>
        )}
      </Card>
      <Card title="Change my password">
        <div className="grid sm:grid-cols-3 gap-3 items-end">
          <Field label="Current password"><Input type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label="New password"><Input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <Button onClick={changePw} disabled={!pw.current_password || !pw.new_password}>Update password</Button>
        </div>
      </Card>
      {can("audit.view") && <AuditLog />}
    </div>
  );
}
