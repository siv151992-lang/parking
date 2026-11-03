import { useState } from "react";
import { ChevronDown, Pencil, Plus, Power, Radar, RotateCw, Trash2, Wifi } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { fmtDateTime, sinceNow } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, SimBadge, Spinner, StatusBadge, Table, useFetch, useToast } from "../components/ui";

const DEFAULT_ZONE = { polygon: [[0.05, 0.25], [0.95, 0.25], [0.95, 0.98], [0.05, 0.98]], trigger_line: 0.62 };
const EMPTY = {
  camera_code: "", name: "", ip_address: "", port: 554, onvif_port: 80, rtsp_url: "", username: "", password: "", location: "",
  direction: "ENTRY", is_simulated: false, is_enabled: true, cooldown_seconds: 60, min_plate_confidence: 0.6, sim_vehicles_per_minute: 4,
  detection_zone: DEFAULT_ZONE, row_id: null,
};

// RTSP path templates for common ANPR / IP camera brands
const BRANDS = [
  { value: "hikvision", label: "Hikvision / HiLook", path: "/Streaming/Channels/101", match: /\/Streaming\/Channels\//i },
  { value: "dahua", label: "Dahua / CP Plus / Amcrest", path: "/cam/realmonitor?channel=1&subtype=0", match: /\/cam\/realmonitor/i },
  { value: "uniview", label: "Uniview", path: "/unicast/c1/s0/live", match: /\/unicast\//i },
  { value: "axis", label: "Axis", path: "/axis-media/media.amp", match: /\/axis-media\//i },
  { value: "other", label: "Other (enter RTSP URL)" },
];
const detectBrand = (url) => (url ? BRANDS.find((b) => b.match?.test(url))?.value || "other" : "hikvision");

function cameraUrl(f) {
  if (f.brand === "other") return f.rtsp_url.trim();
  const b = BRANDS.find((x) => x.value === f.brand);
  const ip = f.ip_address.trim();
  if (!ip) return "";
  const port = Number(f.port) || 554;
  return `rtsp://${ip}${port === 554 ? "" : `:${port}`}${b.path}`;
}

// "Camera position" combines the direction with the gate / row the camera watches.
function positions(rows) {
  return [
    { value: "gate:ENTRY", label: "Main gate · vehicles coming in" },
    { value: "gate:EXIT", label: "Main gate · vehicles going out" },
    ...rows.flatMap((r) => [
      { value: `row:${r.id}:ENTRY`, label: `${r.name} · vehicles driving into the row` },
      { value: `row:${r.id}:EXIT`, label: `${r.name} · vehicles leaving the row` },
    ]),
  ];
}
const positionOf = (c) => (c.row_id ? `row:${c.row_id}:${c.direction}` : `gate:${c.direction}`);
function positionLabel(c, rows) {
  const where = c.row_id ? rows.find((r) => r.id === c.row_id)?.name || "Row" : "Main gate";
  return `${where} · ${c.direction === "ENTRY" ? "in" : "out"}`;
}

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
  const rows = useFetch(() => get("/api/rows").catch(() => []), []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState(null);
  const [discover, setDiscover] = useState(null);
  const [advanced, setAdvanced] = useState(false);
  useLiveRefresh(["camera_status", "detection"], cams.reload, 1500);

  if (!cams.data) return <Spinner />;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const openForm = (f) => {
    setTest(null);
    setAdvanced(false);
    const brand = f.id ? detectBrand(f.rtsp_url) : "hikvision";
    let { ip_address = "", port = 554 } = f;
    if (brand !== "other" && f.rtsp_url) {
      // take the host and port from the saved URL so the rebuilt URL matches it
      const m = f.rtsp_url.match(/^rtsp:\/\/(?:[^@/]*@)?([^:/?]+)(?::(\d+))?/i);
      if (m) { ip_address = m[1]; port = Number(m[2]) || 554; }
    }
    setForm({ ...EMPTY, ...f, ip_address, port, password: "", brand });
  };
  const url = form ? cameraUrl(form) : "";
  const rowList = rows.data || [];
  const setPosition = (v) => {
    const [kind, a, b] = v.split(":");
    setForm((f) => ({ ...f, row_id: kind === "row" ? Number(a) : null, direction: kind === "row" ? b : a }));
  };

  const save = async () => {
    if (!form.name.trim()) return toast("Enter a camera name", "error");
    if (!form.is_simulated && !url) return toast(form.brand === "other" ? "Enter the RTSP URL" : "Enter the camera IP address", "error");
    setSaving(true);
    const body = { ...form, camera_code: form.camera_code.trim(),
      rtsp_url: form.is_simulated ? form.rtsp_url : url, port: Number(form.port), onvif_port: Number(form.onvif_port), cooldown_seconds: Number(form.cooldown_seconds),
      min_plate_confidence: Number(form.min_plate_confidence), sim_vehicles_per_minute: Number(form.sim_vehicles_per_minute) };
    delete body.id;
    delete body.brand;
    if (form.id && !body.password) delete body.password;
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
      const r = await post("/api/cameras/test-stream", { rtsp_url: url, username: form.username, password: form.password || "", camera_id: form.id || null });
      if (r.rtsp_url) setForm((f) => ({ ...f, brand: "other", rtsp_url: r.rtsp_url }));
      setTest(r);
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
        setForm((f) => ({ ...f, brand: "other", rtsp_url: r.profiles[0].rtsp_url }));
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
      <PageHeader title="Cameras" subtitle="Main gate cameras count the whole car park; row cameras count the free spaces of one row">
        {manage && <Button variant="secondary" icon={Radar} onClick={runDiscover}>Discover ONVIF</Button>}
        {manage && <Button icon={Plus} onClick={() => openForm({})}>Add camera</Button>}
      </PageHeader>

      <Card bodyClass="p-0">
        <Table
          rows={cams.data}
          columns={[
            { key: "name", label: "Camera", render: (c) => <div><p className="font-medium text-slate-900 flex items-center gap-1.5">{c.name} <SimBadge show={c.is_simulated} /></p><p className="text-xs text-slate-500">{c.camera_code} · {c.location || "—"}</p></div> },
            { key: "direction", label: "Position", render: (c) => <span className="text-sm whitespace-nowrap">{positionLabel(c, rowList)}</span> },
            { key: "addr", label: "Address", render: (c) => <span className="text-xs font-mono">{c.is_simulated ? "sim://" : c.ip_address || "—"}</span> },
            { key: "status", label: "Status", render: (c) => <div><StatusBadge status={c.status} />{c.last_error && c.status !== "ONLINE" && <p className="text-[11px] text-red-600 max-w-[220px] truncate" title={c.last_error}>{c.last_error}</p>}</div> },
            { key: "rt", label: "Stream", render: (c) => <span className="text-xs tabular-nums">{c.runtime?.fps ? `${c.runtime.fps} fps · ${c.runtime.reconnects} reconnects` : "—"}</span> },
            { key: "last", label: "Last detection", render: (c) => <span title={fmtDateTime(c.last_detection_at)} className="text-xs">{sinceNow(c.last_detection_at)}</span> },
            { key: "cfg", label: "Cooldown / Min conf", render: (c) => <span className="text-xs">{c.cooldown_seconds}s · {Math.round(c.min_plate_confidence * 100)}%</span> },
            ...(manage ? [{ key: "actions", label: "", render: (c) => (
              <div className="flex gap-1 justify-end">
                <Button size="sm" variant="ghost" icon={Pencil} title="Edit" onClick={() => openForm(c)} />
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
          <div className="space-y-4">
            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="Camera name *"><Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Main gate entry" autoFocus /></Field>
              <Field label="Camera position *" hint={rowList.length ? undefined : "Add rows under Parking Spaces to put cameras at row entrances"}>
                <Select value={positionOf(form)} onChange={(e) => setPosition(e.target.value)} options={positions(rowList)} />
              </Field>
            </div>

            {form.is_simulated ? (
              <p className="text-sm bg-violet-50 text-violet-800 rounded-lg p-3">
                This is a <b>simulated test camera</b>. It generates fake traffic, and everything it records is labelled <b>SIM</b>. Change this under Advanced settings.
              </p>
            ) : (
              <div className="grid sm:grid-cols-2 gap-3">
                {form.brand === "other" ? (
                  <Field label="RTSP URL *" hint="From the camera's manual, e.g. rtsp://192.168.1.64:554/stream1">
                    <Input value={form.rtsp_url} onChange={(e) => set("rtsp_url", e.target.value)} placeholder="rtsp://…" />
                  </Field>
                ) : (
                  <Field label="Camera IP address *" hint="Shown in the camera's web page or your router">
                    <Input value={form.ip_address} onChange={(e) => set("ip_address", e.target.value)} placeholder="192.168.1.64" />
                  </Field>
                )}
                <Field label="Username"><Input value={form.username} onChange={(e) => set("username", e.target.value)} placeholder="admin" autoComplete="off" /></Field>
                <Field label="Password" hint={form.id && form.has_password ? "Leave empty to keep the saved password" : undefined}>
                  <Input type="password" value={form.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" />
                </Field>
                <p className="text-xs text-slate-500 self-end pb-2">Any brand works: the right video address is found automatically.</p>
                <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
                  <Button variant="secondary" icon={Wifi} onClick={testStream} disabled={!url} loading={test?.loading}>Test connection</Button>
                  {url && <span className="text-xs text-slate-500 font-mono break-all">{url}</span>}
                </div>
                {test && !test.loading && (
                  <div className="sm:col-span-2 text-sm">
                    {test.ok ? (
                      <div className="flex gap-3 items-start"><img src={test.snapshot} alt="Camera snapshot" className="w-48 rounded" /><div className="text-emerald-700 space-y-1"><p>Connected · {test.width}×{test.height} · {test.fps} fps. Click Save camera.</p>{test.rtsp_url && <p className="text-xs">Found this camera's stream at <span className="font-mono break-all">{test.rtsp_url}</span>. It has been filled in for you.</p>}</div></div>
                    ) : (
                      <p className="text-red-600">Could not connect: {test.error}</p>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="border-t border-slate-200 pt-3">
              <button type="button" onClick={() => setAdvanced((v) => !v)} className="flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900">
                <ChevronDown size={16} className={`transition-transform ${advanced ? "rotate-180" : ""}`} /> Advanced settings
              </button>
              {advanced && (
                <div className="space-y-4 mt-4">
                  <div className="grid sm:grid-cols-3 gap-3">
                    <Field label="Camera ID" hint="Leave empty to create one automatically">
                      <Input value={form.camera_code} onChange={(e) => set("camera_code", e.target.value)} />
                    </Field>
                    <Field label="Location" className="sm:col-span-2"><Input value={form.location} onChange={(e) => set("location", e.target.value)} placeholder="Gate 1 - North" /></Field>
                  </div>
                  {!form.is_simulated && (
                    <div className="grid sm:grid-cols-3 gap-3">
                      <Field label="Camera brand (video address)" className="sm:col-span-3">
                        <Select value={form.brand} onChange={(e) => set("brand", e.target.value)} options={BRANDS.map(({ value, label }) => ({ value, label }))} />
                      </Field>
                      {form.brand !== "other" && <Field label="RTSP port"><Input type="number" value={form.port} onChange={(e) => set("port", e.target.value)} /></Field>}
                      <Field label="ONVIF port"><Input type="number" value={form.onvif_port} onChange={(e) => set("onvif_port", e.target.value)} /></Field>
                      <div className="flex items-end"><Button variant="secondary" className="w-full" icon={Radar} onClick={probe} disabled={!form.ip_address}>Get URL via ONVIF</Button></div>
                    </div>
                  )}
                  {form.is_simulated && (
                    <Field label="Simulated vehicles per minute" className="sm:w-1/3"><Input type="number" step="0.5" min="0.5" value={form.sim_vehicles_per_minute} onChange={(e) => set("sim_vehicles_per_minute", e.target.value)} /></Field>
                  )}
                  <div className="grid sm:grid-cols-3 gap-3">
                    <Field label="Cooldown (seconds)" hint="Same plate in the same direction is ignored within this window"><Input type="number" min="0" value={form.cooldown_seconds} onChange={(e) => set("cooldown_seconds", e.target.value)} /></Field>
                    <Field label="Min. plate confidence" hint="Reads below this are counted but flagged unread"><Input type="number" step="0.05" min="0" max="1" value={form.min_plate_confidence} onChange={(e) => set("min_plate_confidence", e.target.value)} /></Field>
                    <div className="space-y-2 self-end pb-2 text-sm">
                      <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_enabled} onChange={(e) => set("is_enabled", e.target.checked)} /> Enabled</label>
                      <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_simulated} onChange={(e) => set("is_simulated", e.target.checked)} /> Simulated test camera</label>
                    </div>
                  </div>
                  <ZoneEditor zone={form.detection_zone} onChange={(z) => set("detection_zone", z)} />
                </div>
              )}
            </div>
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
                <Button size="sm" onClick={() => { setDiscover(null); openForm({ ip_address: d.ip_address, onvif_port: d.onvif_port, name: d.name || "" }); }}>Add</Button>
              </li>
            ))}
          </ul>
        ))}
      </Modal>
    </div>
  );
}
