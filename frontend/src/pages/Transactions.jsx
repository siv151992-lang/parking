import { useState } from "react";
import { Ban, Link2, Plus, Search } from "lucide-react";
import { get, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { fmtDateTime, fmtDuration, VEHICLE_TYPES } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Pagination, Plate, Select, Spinner, StatusBadge, Table, useFetch, useToast } from "../components/ui";

const PAGE = 25;
const vtOptions = [{ value: "", label: "All types" }, ...Object.entries(VEHICLE_TYPES).map(([value, label]) => ({ value, label }))];
const srcOptions = [{ value: "", label: "All sources" }, { value: "ANPR", label: "ANPR camera" }, { value: "SIMULATED", label: "Simulated" }, { value: "MANUAL", label: "Manual" }, { value: "SYSTEM", label: "System" }];

function Filters({ f, setF, cams, statusOptions }) {
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value, page: 1 });
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2 p-3 border-b border-slate-100">
      <div className="relative col-span-2 md:col-span-1">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <Input placeholder="Registration no." value={f.plate} onChange={upd("plate")} style={{ paddingLeft: 30 }} />
      </div>
      <Input type="date" value={f.start} onChange={upd("start")} aria-label="From date" />
      <Input type="date" value={f.end} onChange={upd("end")} aria-label="To date" />
      <Select value={f.camera_id} onChange={upd("camera_id")} options={[{ value: "", label: "All cameras" }, ...cams.map((c) => ({ value: c.id, label: c.name }))]} />
      <Select value={f.vehicle_type} onChange={upd("vehicle_type")} options={vtOptions} />
      <Select value={f.source} onChange={upd("source")} options={srcOptions} />
      <Select value={f.status} onChange={upd("status")} options={statusOptions} />
    </div>
  );
}

function useTx(kind) {
  const [f, setF] = useState({ plate: "", start: "", end: "", camera_id: "", vehicle_type: "", source: "", status: "", page: 1 });
  const data = useFetch(() => get(`/api/${kind}`, { ...f, page_size: PAGE }), [JSON.stringify(f)]);
  const cams = useFetch(() => get("/api/cameras").catch(() => []), []);
  useLiveRefresh([kind === "entries" ? "entry" : "exit", `${kind === "entries" ? "entry" : "exit"}_updated`], data.reload, 700);
  return { f, setF, data, cams: (cams.data || []).filter((c) => c.direction === (kind === "entries" ? "ENTRY" : "EXIT")) };
}

function CancelModal({ target, kind, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (!target) return null;
  const submit = async () => {
    setBusy(true);
    try {
      await post(`/api/${kind}/${target.id}/cancel`, { reason });
      toast(kind === "entries" ? "Entry cancelled — vehicle removed from count" : "Exit cancelled — vehicle counted as inside again", "success");
      onDone();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={`Cancel ${kind === "entries" ? "entry" : "exit"} #${target.id}`}
      footer={<><Button variant="secondary" onClick={onClose}>Back</Button><Button variant="danger" onClick={submit} loading={busy} disabled={reason.trim().length < 3}>Cancel transaction</Button></>}>
      <p className="text-sm text-slate-600 mb-3">
        <Plate value={target.plate_number} /> at {fmtDateTime(target.timestamp)}. This correction is recorded in the audit log.
      </p>
      <Field label="Reason (required)"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. false detection caused by reflection" autoFocus /></Field>
    </Modal>
  );
}

export function VehicleEntry() {
  const { can } = useAuth();
  const toast = useToast();
  const { f, setF, data, cams } = useTx("entries");
  const [manual, setManual] = useState(null);
  const [cancel, setCancel] = useState(null);

  const submitManual = async () => {
    try {
      await post("/api/entries/manual", { ...manual, camera_id: manual.camera_id ? Number(manual.camera_id) : null, timestamp: manual.timestamp ? new Date(manual.timestamp).toISOString() : null });
      toast(`Entry recorded for ${manual.plate_number}`, "success");
      setManual(null);
      data.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Vehicle Entry" subtitle="Every entry transaction, from ANPR cameras, simulation or manual input">
        {can("transactions.manual") && <Button icon={Plus} onClick={() => setManual({ plate_number: "", vehicle_type: "CAR", timestamp: "", camera_id: "", notes: "" })}>Manual entry</Button>}
      </PageHeader>
      <Card bodyClass="p-0">
        <Filters f={f} setF={setF} cams={cams} statusOptions={[{ value: "", label: "All statuses" }, { value: "VALID", label: "Valid" }, { value: "CANCELLED", label: "Cancelled" }]} />
        {!data.data ? <Spinner /> : (
          <>
            <Table rows={data.data.items} columns={[
              { key: "timestamp", label: "Entry time", render: (t) => fmtDateTime(t.timestamp) },
              { key: "plate_number", label: "Reg. No.", render: (t) => <Plate value={t.plate_number} /> },
              { key: "vehicle_type", label: "Type", render: (t) => VEHICLE_TYPES[t.vehicle_type] },
              { key: "category", label: "Parking", render: (t) => <Badge color={t.category === "RESERVED" ? "violet" : "slate"}>{t.category}</Badge> },
              { key: "camera_name", label: "Camera" },
              { key: "confidence", label: "Conf.", render: (t) => `${Math.round(t.confidence * 100)}%` },
              { key: "source", label: "Source", render: (t) => <Badge color={t.source === "SIMULATED" ? "violet" : t.source === "MANUAL" ? "amber" : "blue"}>{t.source}</Badge> },
              { key: "status", label: "Status", render: (t) => <StatusBadge status={t.status} /> },
              { key: "a", label: "", render: (t) => can("transactions.correct") && t.status === "VALID" && <Button size="sm" variant="ghost" icon={Ban} onClick={() => setCancel(t)}>Cancel</Button> },
            ]} />
            <Pagination page={f.page} pageSize={PAGE} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
          </>
        )}
      </Card>
      <CancelModal target={cancel} kind="entries" onClose={() => setCancel(null)} onDone={() => { setCancel(null); data.reload(); }} />
      <Modal open={!!manual} onClose={() => setManual(null)} title="Manual vehicle entry"
        footer={<><Button variant="secondary" onClick={() => setManual(null)}>Cancel</Button><Button onClick={submitManual} disabled={!manual?.plate_number}>Record entry</Button></>}>
        {manual && (
          <div className="space-y-3">
            <Field label="Registration number *"><Input value={manual.plate_number} onChange={(e) => setManual({ ...manual, plate_number: e.target.value.toUpperCase() })} placeholder="MH12AB1234" autoFocus /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Vehicle type"><Select value={manual.vehicle_type} onChange={(e) => setManual({ ...manual, vehicle_type: e.target.value })} options={vtOptions.slice(1)} /></Field>
              <Field label="Gate / camera"><Select value={manual.camera_id} onChange={(e) => setManual({ ...manual, camera_id: e.target.value })} options={[{ value: "", label: "Manual (no camera)" }, ...cams.map((c) => ({ value: c.id, label: c.name }))]} /></Field>
            </div>
            <Field label="Entry time" hint="Leave empty for now"><Input type="datetime-local" value={manual.timestamp} onChange={(e) => setManual({ ...manual, timestamp: e.target.value })} /></Field>
            <Field label="Notes"><Input value={manual.notes} onChange={(e) => setManual({ ...manual, notes: e.target.value })} placeholder="e.g. camera offline, entered via barrier override" /></Field>
          </div>
        )}
      </Modal>
    </div>
  );
}

function ResolveModal({ exit, onClose, onDone }) {
  const toast = useToast();
  const cands = useFetch(() => get(`/api/exits/${exit.id}/candidates`), [exit.id]);
  const link = async (sid) => {
    try {
      await post(`/api/exits/${exit.id}/resolve`, { session_id: sid });
      toast("Exit linked — session closed and count corrected", "success");
      onDone();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <Modal open onClose={onClose} title="Resolve unmatched exit" wide>
      <p className="text-sm text-slate-600 mb-3">Exit read as <Plate value={exit.plate_number} /> at {fmtDateTime(exit.timestamp)} ({exit.camera_name}). Pick the parking session it belongs to — closest matches first.</p>
      {!cands.data ? <Spinner /> : (
        <Table rows={cands.data} columns={[
          { key: "plate_number", label: "Session plate", render: (s) => <Plate value={s.plate_number} /> },
          { key: "distance", label: "Similarity", render: (s) => s.distance === 0 ? <Badge color="green">exact (OCR-folded)</Badge> : s.distance <= 2 ? <Badge color="amber">{s.distance} char diff</Badge> : <Badge>{s.plate_number ? "different" : "unread"}</Badge> },
          { key: "vehicle_type", label: "Type", render: (s) => VEHICLE_TYPES[s.vehicle_type] },
          { key: "entry_time", label: "Entered", render: (s) => fmtDateTime(s.entry_time) },
          { key: "entry_camera", label: "Entry camera" },
          { key: "a", label: "", render: (s) => <Button size="sm" icon={Link2} onClick={() => link(s.id)}>Link</Button> },
        ]} empty="No active sessions" />
      )}
    </Modal>
  );
}

export function VehicleExit() {
  const { can } = useAuth();
  const toast = useToast();
  const { f, setF, data, cams } = useTx("exits");
  const [manual, setManual] = useState(null);
  const [cancel, setCancel] = useState(null);
  const [resolve, setResolve] = useState(null);
  const active = useFetch(() => (manual ? get("/api/sessions", { status: "ACTIVE", plate: manual.plate_number, page_size: 8 }) : Promise.resolve(null)), [manual?.plate_number, !!manual]);

  const submitManual = async (sessionId) => {
    try {
      await post("/api/exits/manual", { session_id: sessionId, timestamp: manual.timestamp ? new Date(manual.timestamp).toISOString() : null, notes: manual.notes });
      toast("Exit recorded", "success");
      setManual(null);
      data.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Vehicle Exit" subtitle="Exits only reduce the vehicle count when matched to an active parking session">
        <Button variant="secondary" onClick={() => setF({ ...f, status: f.status === "UNMATCHED" ? "" : "UNMATCHED", page: 1 })}>{f.status === "UNMATCHED" ? "Show all" : "Show unmatched only"}</Button>
        {can("transactions.manual") && <Button icon={Plus} onClick={() => setManual({ plate_number: "", timestamp: "", notes: "" })}>Manual exit</Button>}
      </PageHeader>
      <Card bodyClass="p-0">
        <Filters f={f} setF={setF} cams={cams} statusOptions={[{ value: "", label: "All statuses" }, ...["MATCHED", "FUZZY_MATCHED", "UNREAD_MATCHED", "MANUAL_MATCHED", "AUTO_CLOSED", "UNMATCHED", "CANCELLED"].map((s) => ({ value: s, label: s.replaceAll("_", " ") }))]} />
        {!data.data ? <Spinner /> : (
          <>
            <Table rows={data.data.items} columns={[
              { key: "timestamp", label: "Exit time", render: (t) => fmtDateTime(t.timestamp) },
              { key: "plate_number", label: "Reg. No.", render: (t) => <Plate value={t.plate_number} /> },
              { key: "vehicle_type", label: "Type", render: (t) => VEHICLE_TYPES[t.vehicle_type] },
              { key: "camera_name", label: "Camera" },
              { key: "confidence", label: "Conf.", render: (t) => `${Math.round(t.confidence * 100)}%` },
              { key: "source", label: "Source", render: (t) => <Badge color={t.source === "SIMULATED" ? "violet" : t.source === "MANUAL" ? "amber" : "blue"}>{t.source}</Badge> },
              { key: "status", label: "Match", render: (t) => <StatusBadge status={t.status} /> },
              { key: "session_id", label: "Session", render: (t) => (t.session_id ? `#${t.session_id}` : "—") },
              { key: "a", label: "", render: (t) => (
                <div className="flex gap-1 justify-end">
                  {t.status === "UNMATCHED" && can("transactions.manual") && <Button size="sm" icon={Link2} onClick={() => setResolve(t)}>Resolve</Button>}
                  {t.status !== "CANCELLED" && t.status !== "UNMATCHED" && can("transactions.correct") && <Button size="sm" variant="ghost" icon={Ban} onClick={() => setCancel(t)}>Cancel</Button>}
                </div>
              ) },
            ]} />
            <Pagination page={f.page} pageSize={PAGE} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
          </>
        )}
      </Card>
      <CancelModal target={cancel} kind="exits" onClose={() => setCancel(null)} onDone={() => { setCancel(null); data.reload(); }} />
      {resolve && <ResolveModal exit={resolve} onClose={() => setResolve(null)} onDone={() => { setResolve(null); data.reload(); }} />}
      <Modal open={!!manual} onClose={() => setManual(null)} title="Manual vehicle exit" wide>
        {manual && (
          <div className="space-y-3">
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Search vehicle inside"><Input value={manual.plate_number} onChange={(e) => setManual({ ...manual, plate_number: e.target.value.toUpperCase() })} placeholder="Registration no." autoFocus /></Field>
              <Field label="Exit time" hint="Leave empty for now"><Input type="datetime-local" value={manual.timestamp} onChange={(e) => setManual({ ...manual, timestamp: e.target.value })} /></Field>
              <Field label="Notes"><Input value={manual.notes} onChange={(e) => setManual({ ...manual, notes: e.target.value })} /></Field>
            </div>
            {active.data && (
              <Table rows={active.data.items} columns={[
                { key: "plate_number", label: "Reg. No.", render: (s) => <Plate value={s.plate_number} /> },
                { key: "vehicle_type", label: "Type", render: (s) => VEHICLE_TYPES[s.vehicle_type] },
                { key: "entry_time", label: "Entered", render: (s) => fmtDateTime(s.entry_time) },
                { key: "dur", label: "Parked", render: (s) => fmtDuration((Date.now() - new Date(s.entry_time)) / 1000) },
                { key: "a", label: "", render: (s) => <Button size="sm" onClick={() => submitManual(s.id)}>Record exit</Button> },
              ]} empty="No vehicles inside match this search" />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
