import { useState } from "react";
import { Check, Pencil, Plus, Search } from "lucide-react";
import { authUrl, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { CATEGORIES, fmtDateTime, fmtDuration, VEHICLE_TYPES } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Pagination, Plate, Select, SimBadge, Spinner, StatusBadge, Table, Thumb, useFetch, useToast } from "../components/ui";

const PAGE = 25;

export function VehicleDetail({ plate, onClose }) {
  const h = useFetch(() => get(`/api/vehicles/history/${encodeURIComponent(plate)}`), [plate]);
  return (
    <Modal open onClose={onClose} title={<span className="flex items-center gap-2">Movement history <Plate value={plate} /></span>} wide>
      {!h.data ? <Spinner /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            {[
              ["Visits", h.data.stats.visits],
              ["Avg. stay", fmtDuration(h.data.stats.avg_duration_seconds)],
              ["Currently", h.data.stats.currently_inside ? "Inside" : "Outside"],
              ["Status", h.data.vehicle?.is_blacklisted ? "Blacklisted" : h.data.vehicle?.is_reserved ? "Reserved" : "Regular"],
            ].map(([k, v]) => (
              <div key={k} className="bg-slate-50 rounded-lg py-2"><p className="text-[11px] text-slate-500">{k}</p><p className="font-semibold text-slate-900">{v}</p></div>
            ))}
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Timeline</h4>
              <ol className="relative border-l-2 border-slate-200 ml-2 space-y-3 max-h-80 overflow-y-auto pr-2">
                {h.data.timeline.map((e, i) => (
                  <li key={i} className="ml-4">
                    <span className={`absolute -left-[7px] mt-1 w-3 h-3 rounded-full ${e.type === "ENTRY" ? "bg-[#2a78d6]" : "bg-[#eb6834]"}`} />
                    <p className="text-sm"><b>{e.type}</b> · {e.camera} <StatusBadge status={e.status} /></p>
                    <p className="text-xs text-slate-500">{fmtDateTime(e.time)} · {e.source} · session #{e.session_id ?? "—"}</p>
                  </li>
                ))}
                {h.data.timeline.length === 0 && <li className="ml-4 text-sm text-slate-400">No movements</li>}
              </ol>
            </div>
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Captured images</h4>
              <div className="grid grid-cols-3 gap-2 max-h-80 overflow-y-auto">
                {h.data.detections.filter((d) => d.vehicle_image).slice(0, 18).map((d) => (
                  <div key={d.id}>
                    <Thumb src={authUrl(d.vehicle_image)} alt="vehicle" className="w-full h-16" />
                    <p className="text-[10px] text-slate-500 mt-0.5">{d.direction} {fmtDateTime(d.detected_at)}</p>
                  </div>
                ))}
                {!h.data.detections.some((d) => d.vehicle_image) && <p className="col-span-3 text-sm text-slate-400">No images</p>}
              </div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Sessions({ onPlate }) {
  const [f, setF] = useState({ plate: "", start: "", end: "", status: "", category: "", vehicle_type: "", include_simulated: "true", page: 1 });
  const data = useFetch(() => get("/api/sessions", { ...f, page_size: PAGE }), [JSON.stringify(f)]);
  useLiveRefresh(["entry", "exit", "session_updated"], data.reload, 1000);
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value, page: 1 });
  return (
    <Card bodyClass="p-0">
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2 p-3 border-b border-slate-100">
        <div className="relative col-span-2 md:col-span-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input placeholder="Registration no." value={f.plate} onChange={upd("plate")} style={{ paddingLeft: 30 }} />
        </div>
        <Input type="date" value={f.start} onChange={upd("start")} aria-label="From" />
        <Input type="date" value={f.end} onChange={upd("end")} aria-label="To" />
        <Select value={f.status} onChange={upd("status")} options={[{ value: "", label: "All (entry & exit)" }, { value: "ACTIVE", label: "Inside (active)" }, { value: "CLOSED", label: "Exited (closed)" }, { value: "CANCELLED", label: "Cancelled" }]} />
        <Select value={f.category} onChange={upd("category")} options={[{ value: "", label: "All categories" }, ...Object.entries(CATEGORIES).map(([value, label]) => ({ value, label }))]} />
        <Select value={f.vehicle_type} onChange={upd("vehicle_type")} options={[{ value: "", label: "All types" }, ...Object.entries(VEHICLE_TYPES).map(([value, label]) => ({ value, label }))]} />
        <Select value={f.include_simulated} onChange={upd("include_simulated")} options={[{ value: "true", label: "Real + simulated" }, { value: "false", label: "Real cameras only" }]} />
      </div>
      {!data.data ? <Spinner /> : (
        <>
          <Table rows={data.data.items} onRowClick={(s) => s.plate_number && onPlate(s.plate_number)} columns={[
            { key: "img", label: "Vehicle", render: (s) => <Thumb src={authUrl(s.entry_vehicle_image)} alt="vehicle" className="w-14 h-9" /> },
            { key: "plate_number", label: "Reg. No.", render: (s) => <span className="flex items-center gap-1.5"><Plate value={s.plate_number} /><SimBadge show={s.is_simulated} />{s.needs_review && <Badge color="amber">review</Badge>}</span> },
            { key: "vehicle_type", label: "Category", render: (s) => <span>{VEHICLE_TYPES[s.vehicle_type]}<span className="text-xs text-slate-400"> · {CATEGORIES[s.category]}</span></span> },
            { key: "entry_time", label: "Entry", render: (s) => <div><p>{fmtDateTime(s.entry_time)}</p><p className="text-[11px] text-slate-400">{s.entry_camera || "Manual"}</p></div> },
            { key: "exit_time", label: "Exit", render: (s) => s.exit_time ? <div><p>{fmtDateTime(s.exit_time)}</p><p className="text-[11px] text-slate-400">{s.exit_camera || "Manual/System"}</p></div> : "—" },
            { key: "duration", label: "Duration", render: (s) => fmtDuration(s.duration_seconds ?? (s.status === "ACTIVE" ? (Date.now() - new Date(s.entry_time)) / 1000 : null)) },
            { key: "conf", label: "Conf.", render: (s) => `${Math.round(s.entry_confidence * 100)}%` },
            { key: "status", label: "Status", render: (s) => <StatusBadge status={s.status} /> },
          ]} />
          <Pagination page={f.page} pageSize={PAGE} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
        </>
      )}
    </Card>
  );
}

function ReviewQueue() {
  const { can } = useAuth();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const data = useFetch(() => get("/api/detections", { needs_review: true, page, page_size: PAGE }), [page]);
  const [edit, setEdit] = useState(null);
  useLiveRefresh(["detection"], data.reload, 1500);
  const submit = async (d, corrected, vtype) => {
    try {
      await post(`/api/detections/${d.id}/review`, { corrected_plate: corrected || null, vehicle_type: vtype || null });
      toast(corrected ? `Corrected to ${corrected.toUpperCase()}` : "Detection confirmed", "success");
      setEdit(null);
      data.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <Card bodyClass="p-0">
      <p className="px-4 py-3 text-xs text-slate-500 border-b border-slate-100">
        Unreadable / low-confidence plates, fuzzy matches and unmatched exits. Correcting a plate updates the linked parking session and, for unmatched exits, closes the matching session automatically.
      </p>
      {!data.data ? <Spinner /> : (
        <>
          <Table rows={data.data.items} columns={[
            { key: "v", label: "Vehicle", render: (d) => <Thumb src={authUrl(d.vehicle_image)} alt="vehicle" className="w-20 h-12" /> },
            { key: "p", label: "Plate crop", render: (d) => <Thumb src={authUrl(d.plate_image)} alt="plate" className="w-28 h-9" /> },
            { key: "plate_number", label: "Read as", render: (d) => <div><Plate value={d.plate_number} />{d.raw_plate_text && d.raw_plate_text !== d.plate_number && <p className="text-[11px] text-slate-400">raw: {d.raw_plate_text}</p>}</div> },
            { key: "plate_confidence", label: "Conf.", render: (d) => `${Math.round(d.plate_confidence * 100)}%` },
            { key: "camera_name", label: "Camera", render: (d) => <span>{d.camera_name} <StatusBadge status={d.direction} /></span> },
            { key: "status_reason", label: "Reason", render: (d) => <span className="text-xs">{d.status_reason || d.status}</span> },
            { key: "detected_at", label: "Time", render: (d) => fmtDateTime(d.detected_at) },
            { key: "a", label: "", render: (d) => can("detections.review") && (
              <div className="flex gap-1">
                <Button size="sm" icon={Pencil} onClick={() => setEdit({ d, plate: d.plate_number || d.raw_plate_text || "", vtype: d.vehicle_type })}>Correct</Button>
                <Button size="sm" variant="ghost" icon={Check} title="Confirm as correct" onClick={() => submit(d, null, null)} />
              </div>
            ) },
          ]} empty="Nothing to review" />
          <Pagination page={page} pageSize={PAGE} total={data.data.total} onChange={setPage} />
        </>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title="Correct detection"
        footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={() => submit(edit.d, edit.plate, edit.vtype)}>Save correction</Button></>}>
        {edit && (
          <div className="space-y-3">
            <Thumb src={authUrl(edit.d.plate_image)} alt="plate" className="w-full h-24 object-contain bg-slate-900" />
            <Field label="Correct registration number"><Input value={edit.plate} onChange={(e) => setEdit({ ...edit, plate: e.target.value.toUpperCase() })} autoFocus /></Field>
            <Field label="Vehicle type"><Select value={edit.vtype} onChange={(e) => setEdit({ ...edit, vtype: e.target.value })} options={Object.entries(VEHICLE_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
          </div>
        )}
      </Modal>
    </Card>
  );
}

function Registry({ onPlate }) {
  const { can } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ q: "", flag: "", page: 1 });
  const data = useFetch(() => get("/api/vehicles", { ...f, page_size: PAGE }), [JSON.stringify(f)]);
  const [form, setForm] = useState(null);
  const save = async () => {
    try {
      if (form.id) await put(`/api/vehicles/${form.id}`, { vehicle_type: form.vehicle_type, is_reserved: form.is_reserved, is_blacklisted: form.is_blacklisted, owner_name: form.owner_name, notes: form.notes });
      else await post("/api/vehicles", form);
      toast("Vehicle saved", "success");
      setForm(null);
      data.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <Card bodyClass="p-0">
      <div className="flex flex-wrap gap-2 p-3 border-b border-slate-100">
        <div className="w-56"><Input placeholder="Search plate" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} /></div>
        <div className="w-48"><Select value={f.flag} onChange={(e) => setF({ ...f, flag: e.target.value, page: 1 })} options={[{ value: "", label: "All vehicles" }, { value: "reserved", label: "Reserved (whitelist)" }, { value: "blacklisted", label: "Blacklisted" }]} /></div>
        {can("vehicles.manage") && <Button className="ml-auto" icon={Plus} onClick={() => setForm({ plate_number: "", vehicle_type: "CAR", is_reserved: false, is_blacklisted: false, owner_name: "", notes: "" })}>Register vehicle</Button>}
      </div>
      {!data.data ? <Spinner /> : (
        <>
          <Table rows={data.data.items} onRowClick={(v) => onPlate(v.plate_number)} columns={[
            { key: "plate_number", label: "Reg. No.", render: (v) => <Plate value={v.plate_number} /> },
            { key: "vehicle_type", label: "Type", render: (v) => VEHICLE_TYPES[v.vehicle_type] },
            { key: "flags", label: "Flags", render: (v) => <span className="flex gap-1">{v.is_reserved && <Badge color="violet">Reserved</Badge>}{v.is_blacklisted && <Badge color="red">Blacklisted</Badge>}</span> },
            { key: "owner_name", label: "Owner" },
            { key: "total_visits", label: "Visits" },
            { key: "last_seen_at", label: "Last seen", render: (v) => fmtDateTime(v.last_seen_at) },
            { key: "a", label: "", render: (v) => can("vehicles.manage") && <Button size="sm" variant="ghost" icon={Pencil} onClick={(e) => { e.stopPropagation(); setForm({ ...v }); }} /> },
          ]} />
          <Pagination page={f.page} pageSize={PAGE} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
        </>
      )}
      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? `Edit ${form.plate_number}` : "Register vehicle"}
        footer={<><Button variant="secondary" onClick={() => setForm(null)}>Cancel</Button><Button onClick={save}>Save</Button></>}>
        {form && (
          <div className="space-y-3">
            {!form.id && <Field label="Registration number"><Input value={form.plate_number} onChange={(e) => setForm({ ...form, plate_number: e.target.value.toUpperCase() })} /></Field>}
            <Field label="Vehicle type"><Select value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })} options={Object.entries(VEHICLE_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
            <Field label="Owner"><Input value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} /></Field>
            <Field label="Notes"><Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_reserved} onChange={(e) => setForm({ ...form, is_reserved: e.target.checked })} /> Reserved parking (counts against the Reserved category)</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_blacklisted} onChange={(e) => setForm({ ...form, is_blacklisted: e.target.checked })} /> Blacklisted (raises a suspicious-vehicle alert on detection)</label>
          </div>
        )}
      </Modal>
    </Card>
  );
}

export default function VehicleHistory() {
  const [tab, setTab] = useState("sessions");
  const [plate, setPlate] = useState(null);
  const tabs = [["sessions", "Parking sessions"], ["review", "Review queue"], ["registry", "Registered vehicles"]];
  return (
    <div className="space-y-5">
      <PageHeader title="Vehicle History" subtitle="Search movements by registration number, date, category or entry/exit status. Click a row for the full movement history." />
      <div className="flex gap-1 border-b border-slate-200 overflow-x-auto">
        {tabs.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${tab === k ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-700"}`}>{l}</button>
        ))}
      </div>
      {tab === "sessions" && <Sessions onPlate={setPlate} />}
      {tab === "review" && <ReviewQueue />}
      {tab === "registry" && <Registry onPlate={setPlate} />}
      {plate && <VehicleDetail plate={plate} onClose={() => setPlate(null)} />}
    </div>
  );
}
