import { useState } from "react";
import { Pencil, Plus, Power, Radar, RotateCw, Trash2, Wifi } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { fmtDateTime, sinceNow } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, SimBadge, Spinner, StatusBadge, Table, useFetch, useToast } from "../components/ui";

const DEFAULT_ZONE = { polygon: [[0.05, 0.25], [0.95, 0.25], [0.95, 0.98], [0.05, 0.98]], trigger_line: 0.62 };
const EMPTY = {
  camera_code: "", name: "", ip_address: "", port: 554, onvif_port: 80, rtsp_url: "", username: "", password: "", location: "",
  direction: "ENTRY", is_simulated: false, is_enabled: true, cooldown_seconds: 60, min_plate_confidence: 0.6, sim_vehicles_per_minute: 4,
  detection_zone: DEFAULT_ZONE,
};

function ZoneEditor({ zone, onChange }) {
  const z = zone || DEFAULT_ZONE;
  const [text, setText] = useState(JSON.stringify(z.polygon));
  const [bad, setBad] = useState(false);
  const pts = z.polygon.map(([x, y]) => `${x * 160},${y * 90}`).join(" ");
  return (
    <div className="grid sm:grid-cols-[160px_1fr] gap-3 items-start">
      <svg viewBox="0 0 160 90" className="w-40 h-[90px] bg-slate-800 rounded" role="img" aria-label="Detection zone preview">
        <polygon points={pts} fill="rgba(56,189,248,0.2)" stroke="#38bdf8" strokeWidth="1.5" />
        <line x1="0" x2="160" y1={z.trigger_line * 90} y2={z.trigger_line * 90} stroke="#22c55e" strokeWidth="1.5" />
      </svg>
      <div className="space-y-2">
        <Field label="Zone polygon (normalised [x,y] points, 0–1)" hint="Only vehicles whose bottom-centre is inside this polygon are processed.">
          <Input value={text} className={bad ? "ring-red-400" : ""} onChange={(e) => {
            setText(e.target.value);
            try {
              const p = JSON.parse(e.target.value);
              if (!Array.isArray(p) || p.length < 3 || p.some((q) => q.length !== 2 || q.some((c) => c < 0 || c > 1))) throw new Error();
              setBad(false);
              onChange({ ...z, polygon: p });
            } catch { setBad(true); }
          }} />
        </Field>
        <Field label={`Trigger line: ${Math.round(z.trigger_line * 100)}% of frame height`} hint="A vehicle is counted when it crosses this line (or waits in the zone at a barrier).">
          <input type="range" min="0.1" max="0.95" step="0.01" value={z.trigger_line} onChange={(e) => onChange({ ...z, trigger_line: Number(e.target.value) })} className="w-full accent-navy-700" />
        </Field>
      </div>
    </div>
  );
}

export default function CameraManagement() {
  const { can } = useAuth();
  const manage = can("cameras.manage");
  const toast = useToast();
  const cams = useFetch(() => get("/api/cameras"), []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState(null);
  const [discover, setDiscover] = useState(null);
  useLiveRefresh(["camera_status", "detection"], cams.reload, 1500);

  if (!cams.data) return <Spinner />;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    const body = { ...form, port: Number(form.port), onvif_port: Number(form.onvif_port), cooldown_seconds: Number(form.cooldown_seconds),
      min_plate_confidence: Number(form.min_plate_confidence), sim_vehicles_per_minute: Number(form.sim_vehicles_per_minute) };
    delete body.id;
    try {
      if (form.id) await put(`/api/cameras/${form.id}`, body);
      else await post("/api/cameras", body);
      toast(form.id ? "Camera updated" : "Camera added — connecting…", "success");
      setForm(null);
      cams.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const testStream = async () => {
    setTest({ loading: true });
    try {
      setTest(await post("/api/cameras/test-stream", { rtsp_url: form.rtsp_url, username: form.username, password: form.password || "" }));
    } catch (e) {
      setTest({ ok: false, error: e.message });
    }
  };

  const runDiscover = async () => {
    setDiscover({ loading: true });
    try {
      setDiscover(await post("/api/cameras/onvif/discover"));
    } catch (e) {
      setDiscover({ error: e.message });
    }
  };

  const probe = async () => {
    try {
      const r = await post("/api/cameras/onvif/probe", { ip_address: form.ip_address, onvif_port: Number(form.onvif_port), username: form.username, password: form.password || "" });
      if (r.profiles?.length) {
        set("rtsp_url", r.profiles[0].rtsp_url);
        toast(`Found ${r.profiles.length} stream profile(s); using "${r.profiles[0].profile}"`, "success");
      } else toast("No stream profiles returned", "warning");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const act = async (fn, msg) => {
    try {
      await fn();
      toast(msg, "success");
      cams.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Camera Management" subtitle="IP / ONVIF ANPR cameras over RTSP, plus simulated cameras for testing">
        {manage && <Button variant="secondary" icon={Radar} onClick={runDiscover}>Discover ONVIF</Button>}
        {manage && <Button icon={Plus} onClick={() => { setTest(null); setForm({ ...EMPTY }); }}>Add camera</Button>}
      </PageHeader>

      <Card bodyClass="p-0">
        <Table
          rows={cams.data}
          columns={[
            { key: "name", label: "Camera", render: (c) => <div><p className="font-medium text-slate-900 flex items-center gap-1.5">{c.name} <SimBadge show={c.is_simulated} /></p><p className="text-xs text-slate-500">{c.camera_code} · {c.location || "—"}</p></div> },
            { key: "direction", label: "Direction", render: (c) => <StatusBadge status={c.direction} /> },
            { key: "addr", label: "Address", render: (c) => <span className="text-xs font-mono">{c.is_simulated ? "sim://" : c.ip_address || "—"}</span> },
            { key: "status", label: "Status", render: (c) => <div><StatusBadge status={c.status} />{c.last_error && c.status !== "ONLINE" && <p className="text-[11px] text-red-600 max-w-[220px] truncate" title={c.last_error}>{c.last_error}</p>}</div> },
            { key: "rt", label: "Stream", render: (c) => <span className="text-xs tabular-nums">{c.runtime?.fps ? `${c.runtime.fps} fps · ${c.runtime.reconnects} reconnects` : "—"}</span> },
            { key: "last", label: "Last detection", render: (c) => <span title={fmtDateTime(c.last_detection_at)} className="text-xs">{sinceNow(c.last_detection_at)}</span> },
            { key: "cfg", label: "Cooldown / Min conf", render: (c) => <span className="text-xs">{c.cooldown_seconds}s · {Math.round(c.min_plate_confidence * 100)}%</span> },
            ...(manage ? [{ key: "actions", label: "", render: (c) => (
              <div className="flex gap-1 justify-end">
                <Button size="sm" variant="ghost" icon={Pencil} title="Edit" onClick={() => { setTest(null); setForm({ ...EMPTY, ...c, password: "" }); }} />
                <Button size="sm" variant="ghost" icon={RotateCw} title="Restart / reconnect" onClick={() => act(() => post(`/api/cameras/${c.id}/restart`), "Restarting camera")} />
                <Button size="sm" variant="ghost" icon={Power} title={c.is_enabled ? "Disable" : "Enable"} onClick={() => act(() => put(`/api/cameras/${c.id}`, { is_enabled: !c.is_enabled }), c.is_enabled ? "Camera disabled" : "Camera enabled")} />
                <Button size="sm" variant="ghost" icon={Trash2} title="Delete" onClick={() => window.confirm(`Delete camera ${c.name}? Historic transactions are kept.`) && act(() => del(`/api/cameras/${c.id}`), "Camera deleted")} />
              </div>
            ) }] : []),
          ]}
        />
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? `Edit ${form.name}` : "Add camera"} wide
        footer={<><Button variant="secondary" onClick={() => setForm(null)}>Cancel</Button><Button onClick={save} loading={saving}>Save camera</Button></>}>
        {form && (
          <div className="space-y-5">
            <div className="flex gap-2">
              {[[false, "Real IP camera (RTSP)"], [true, "Simulated camera"]].map(([v, label]) => (
                <button key={label} onClick={() => set("is_simulated", v)} className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium ring-1 ${form.is_simulated === v ? "bg-navy-900 text-white ring-navy-900" : "ring-slate-300 text-slate-600"}`}>{label}</button>
              ))}
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Camera ID *"><Input value={form.camera_code} onChange={(e) => set("camera_code", e.target.value)} placeholder="CAM-EN-03" /></Field>
              <Field label="Camera name *"><Input value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
              <Field label="Direction *"><Select value={form.direction} onChange={(e) => set("direction", e.target.value)} options={[{ value: "ENTRY", label: "ENTRY" }, { value: "EXIT", label: "EXIT" }]} /></Field>
              <Field label="Location" className="sm:col-span-3"><Input value={form.location} onChange={(e) => set("location", e.target.value)} placeholder="Gate 1 - North" /></Field>
            </div>
            {!form.is_simulated ? (
              <div className="grid sm:grid-cols-4 gap-3">
                <Field label="IP address"><Input value={form.ip_address} onChange={(e) => set("ip_address", e.target.value)} placeholder="192.168.1.120" /></Field>
                <Field label="RTSP port"><Input type="number" value={form.port} onChange={(e) => set("port", e.target.value)} /></Field>
                <Field label="ONVIF port"><Input type="number" value={form.onvif_port} onChange={(e) => set("onvif_port", e.target.value)} /></Field>
                <div className="flex items-end"><Button variant="secondary" className="w-full" icon={Radar} onClick={probe} disabled={!form.ip_address}>Get RTSP via ONVIF</Button></div>
                <Field label="RTSP URL *" className="sm:col-span-4" hint="e.g. rtsp://192.168.1.120:554/Streaming/Channels/101 (Hikvision) · rtsp://IP:554/cam/realmonitor?channel=1&subtype=0 (Dahua). A local video file path also works for testing.">
                  <Input value={form.rtsp_url} onChange={(e) => set("rtsp_url", e.target.value)} />
                </Field>
                <Field label="Username"><Input value={form.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" /></Field>
                <Field label="Password" hint={form.id && form.has_password ? "Leave empty to keep the stored password" : undefined}><Input type="password" value={form.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" /></Field>
                <div className="sm:col-span-2 flex items-end"><Button variant="secondary" icon={Wifi} onClick={testStream} disabled={!form.rtsp_url} loading={test?.loading}>Test connection</Button></div>
                {test && !test.loading && (
                  <div className="sm:col-span-4 text-sm">
                    {test.ok ? (
                      <div className="flex gap-3 items-start"><img src={test.snapshot} alt="snapshot" className="w-48 rounded" /><p className="text-emerald-700">Connected · {test.width}×{test.height} · {test.fps} fps</p></div>
                    ) : <p className="text-red-600">Connection failed: {test.error}</p>}
                  </div>
                )}
              </div>
            ) : (
              <div className="grid sm:grid-cols-3 gap-3">
                <Field label="Simulated vehicles per minute" hint="Average arrival rate rendered by the simulator"><Input type="number" step="0.5" min="0.5" value={form.sim_vehicles_per_minute} onChange={(e) => set("sim_vehicles_per_minute", e.target.value)} /></Field>
                <p className="sm:col-span-2 text-xs text-slate-500 self-center bg-violet-50 text-violet-800 rounded-lg p-3">
                  Simulated cameras render synthetic traffic with realistic OCR noise. All their detections and transactions are flagged <b>SIMULATED</b> and can be excluded from reports.
                </p>
              </div>
            )}
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Cooldown (seconds)" hint="Same plate in the same direction is ignored within this window"><Input type="number" min="0" value={form.cooldown_seconds} onChange={(e) => set("cooldown_seconds", e.target.value)} /></Field>
              <Field label="Min. plate confidence" hint="Reads below this are counted but flagged unread"><Input type="number" step="0.05" min="0" max="1" value={form.min_plate_confidence} onChange={(e) => set("min_plate_confidence", e.target.value)} /></Field>
              <label className="flex items-center gap-2 text-sm self-end pb-2"><input type="checkbox" checked={form.is_enabled} onChange={(e) => set("is_enabled", e.target.checked)} /> Enabled</label>
            </div>
            <ZoneEditor zone={form.detection_zone} onChange={(z) => set("detection_zone", z)} />
          </div>
        )}
      </Modal>

      <Modal open={!!discover} onClose={() => setDiscover(null)} title="ONVIF discovery">
        {discover?.loading && <Spinner />}
        {discover?.error && <p className="text-red-600 text-sm">{discover.error}</p>}
        {discover?.devices && (discover.devices.length === 0 ? <p className="text-sm text-slate-500">No ONVIF devices answered on the local network (multicast 239.255.255.250:3702).</p> : (
          <ul className="divide-y divide-slate-100">
            {discover.devices.map((d) => (
              <li key={d.ip_address} className="py-2 flex items-center gap-3 text-sm">
                <div className="flex-1"><p className="font-medium">{d.name || "ONVIF camera"} <Badge>{d.hardware}</Badge></p><p className="text-xs text-slate-500 font-mono">{d.ip_address}:{d.onvif_port}</p></div>
                <Button size="sm" onClick={() => { setDiscover(null); setTest(null); setForm({ ...EMPTY, ip_address: d.ip_address, onvif_port: d.onvif_port, name: d.name || "" }); }}>Add</Button>
              </li>
            ))}
          </ul>
        ))}
      </Modal>
    </div>
  );
}
