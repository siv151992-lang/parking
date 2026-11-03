import { useState } from "react";
import { Columns2, Columns3, Maximize2, RefreshCw, Square, Syringe, VideoOff } from "lucide-react";
import { authUrl, get, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useEvent, useLiveRefresh } from "../lib/realtime";
import { fmtTime, sinceNow, VEHICLE_TYPES } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Plate, Select, SimBadge, Spinner, StatusBadge, Thumb, useFetch, useToast } from "../components/ui";

function CameraTile({ cam, onExpand }) {
  const [key, setKey] = useState(0);
  const [err, setErr] = useState(false);
  const live = cam.status === "ONLINE" || cam.status === "CONNECTING" || cam.status === "OFFLINE";
  return (
    <div className="bg-navy-950 rounded-xl overflow-hidden shadow-sm ring-1 ring-navy-800 flex flex-col">
      <div className="relative aspect-video bg-black flex items-center justify-center">
        {cam.is_enabled && live && !err ? (
          <img key={key} src={authUrl(`/api/cameras/${cam.id}/stream`)} alt={cam.name} className="w-full h-full object-contain" onError={() => setErr(true)} />
        ) : (
          <div className="text-slate-500 flex flex-col items-center gap-2 text-sm">
            <VideoOff size={28} />
            {cam.is_enabled ? "Stream unavailable" : "Camera disabled"}
          </div>
        )}
        <div className="absolute bottom-2 left-2 flex gap-1.5">
          <StatusBadge status={cam.status} />
          <SimBadge show={cam.is_simulated} />
        </div>
        <div className="absolute top-8 right-2 flex gap-1">
          <button className="p-1.5 rounded bg-black/50 text-white hover:bg-black/70" title="Reconnect stream" onClick={() => { setErr(false); setKey((k) => k + 1); }}>
            <RefreshCw size={14} />
          </button>
          <button className="p-1.5 rounded bg-black/50 text-white hover:bg-black/70" title="Expand" onClick={() => onExpand(cam)}>
            <Maximize2 size={14} />
          </button>
        </div>
      </div>
      <div className="px-3 py-2 text-xs text-slate-300 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold text-white">{cam.name}</span>
        <span>{cam.camera_code}</span>
        <Badge color={cam.direction === "ENTRY" ? "green" : "orange"}>{cam.direction}</Badge>
        <span className="ml-auto tabular-nums">{cam.runtime?.fps ? `${cam.runtime.fps} fps` : ""}</span>
        <span>last: {sinceNow(cam.last_detection_at)}</span>
      </div>
      {cam.runtime?.engine && cam.runtime.engine.startsWith("unavailable") && (
        <p className="px-3 pb-2 text-[11px] text-amber-400">Plate reading is off: video only. Add WITH_AI=true to .env and run start.bat again.</p>
      )}
    </div>
  );
}

export default function LiveMonitoring() {
  const { can } = useAuth();
  const toast = useToast();
  const cams = useFetch(() => get("/api/cameras"), []);
  const feed = useFetch(() => get("/api/dashboard/recent-detections", { limit: 25 }), []);
  const [cols, setCols] = useState(2);
  const [filter, setFilter] = useState("ALL");
  const [expanded, setExpanded] = useState(null);
  const [inject, setInject] = useState(null);

  useLiveRefresh(["camera_status"], cams.reload, 300);
  useEvent("detection", (d) => d.status !== "COOLDOWN" && feed.setData((rows) => [d, ...(rows || [])].slice(0, 25)));

  if (!cams.data) return <Spinner />;
  const list = cams.data.filter((c) => filter === "ALL" || c.direction === filter);
  const grid = { 1: "grid-cols-1", 2: "grid-cols-1 lg:grid-cols-2", 3: "grid-cols-1 md:grid-cols-2 2xl:grid-cols-3" }[cols];

  const doInject = async () => {
    try {
      const r = await post("/api/cameras/inject-detection", { ...inject, camera_id: Number(inject.camera_id), plate_number: inject.plate_number || null });
      toast(`Result: ${r.status}${r.match ? ` (${r.match})` : ""}`, r.status === "ENTRY_CREATED" || r.status === "EXIT_RECORDED" ? "success" : "warning");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Live Camera Monitoring" subtitle="Real-time ANPR feeds with detection zone, trigger line and tracked vehicles">
        <div className="flex rounded-lg ring-1 ring-slate-300 bg-white overflow-hidden">
          {["ALL", "ENTRY", "EXIT"].map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1.5 text-xs font-medium ${filter === f ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{f}</button>
          ))}
        </div>
        <div className="flex rounded-lg ring-1 ring-slate-300 bg-white overflow-hidden">
          {[[1, Square], [2, Columns2], [3, Columns3]].map(([n, I]) => (
            <button key={n} onClick={() => setCols(n)} className={`px-2.5 py-1.5 ${cols === n ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`} aria-label={`${n} columns`}><I size={14} /></button>
          ))}
        </div>
        {can("cameras.manage") && (
          <Button size="sm" variant="secondary" icon={Syringe} onClick={() => setInject({ camera_id: cams.data[0]?.id || "", plate_number: "", vehicle_type: "CAR", plate_confidence: 0.92 })}>
            Inject test vehicle
          </Button>
        )}
      </PageHeader>

      <div className="grid 2xl:grid-cols-4 gap-5">
        <div className={`2xl:col-span-3 grid ${grid} gap-4 content-start`}>
          {list.map((c) => <CameraTile key={`${c.id}-${c.status === "ONLINE"}`} cam={c} onExpand={setExpanded} />)}
          {list.length === 0 && <p className="text-slate-500 text-sm">No cameras. Add one in Camera Management.</p>}
        </div>
        <Card title="Live detections" bodyClass="p-0" className="2xl:max-h-[calc(100vh-12rem)] flex flex-col">
          <ul className="divide-y divide-slate-100 overflow-y-auto">
            {(feed.data || []).map((d) => (
              <li key={d.id} className="px-3 py-2.5 flex gap-3 items-center">
                <Thumb src={authUrl(d.vehicle_image)} alt="vehicle" className="w-14 h-10" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Plate value={d.plate_number} />
                    <StatusBadge status={d.direction} />
                    <SimBadge show={d.is_simulated} />
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                    {d.camera_name} · {VEHICLE_TYPES[d.vehicle_type]} · {Math.round(d.plate_confidence * 100)}% · {d.ocr_reads} reads
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <StatusBadge status={d.status} />
                  <p className="text-[11px] text-slate-400 mt-0.5 tabular-nums">{fmtTime(d.detected_at)}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Modal open={!!expanded} onClose={() => setExpanded(null)} title={expanded?.name} wide>
        {expanded && <img src={authUrl(`/api/cameras/${expanded.id}/stream`)} alt={expanded.name} className="w-full rounded-lg bg-black" />}
      </Modal>

      <Modal open={!!inject} onClose={() => setInject(null)} title="Inject a simulated vehicle pass"
        footer={<><Button variant="secondary" onClick={() => setInject(null)}>Close</Button><Button onClick={doInject}>Send through pipeline</Button></>}>
        {inject && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">Pushes one detection through the full counting pipeline (cooldown, duplicate checks, matching). Recorded as SIMULATED.</p>
            <Field label="Camera"><Select value={inject.camera_id} onChange={(e) => setInject({ ...inject, camera_id: e.target.value })} options={cams.data.map((c) => ({ value: c.id, label: `${c.name} (${c.direction})` }))} /></Field>
            <Field label="Registration number" hint="Leave empty to simulate a failed plate read"><Input value={inject.plate_number} onChange={(e) => setInject({ ...inject, plate_number: e.target.value.toUpperCase() })} placeholder="MH12AB1234" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Vehicle type"><Select value={inject.vehicle_type} onChange={(e) => setInject({ ...inject, vehicle_type: e.target.value })} options={Object.entries(VEHICLE_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
              <Field label="OCR confidence"><Input type="number" step="0.01" min="0" max="1" value={inject.plate_confidence} onChange={(e) => setInject({ ...inject, plate_confidence: Number(e.target.value) })} /></Field>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
