import { useState } from "react";
import { Camera, Pencil, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, fmtNum } from "../lib/format";
import { Button, Card, Field, Input, Modal, Plate, SimBadge, Table, useToast } from "../components/ui";

export function rowTone(r) {
  if (r.capacity && r.available === 0) return { bar: "bg-red-600", text: "text-red-700", label: "FULL" };
  if (r.occupancy_pct >= 90) return { bar: "bg-amber-500", text: "text-amber-700", label: "Almost full" };
  return { bar: "bg-emerald-600", text: "text-emerald-700", label: null };
}

/** One row: big free-space number, a bar, and its camera status. */
export function RowCard({ r, onClick }) {
  const tone = rowTone(r);
  const offline = r.cameras.filter((c) => c.status !== "ONLINE");
  return (
    <button type="button" onClick={onClick} disabled={!onClick}
      className="text-left bg-white rounded-xl ring-1 ring-slate-200 p-4 enabled:hover:ring-navy-300 transition w-full">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold text-slate-800">{r.name}</p>
        {tone.label && <span className={`text-[11px] font-bold ${tone.text}`}>{tone.label}</span>}
      </div>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className={`text-4xl font-bold tabular-nums ${tone.text}`}>{fmtNum(r.available)}</span>
        <span className="text-sm text-slate-500">free</span>
      </p>
      <div className="mt-3 h-2.5 rounded-full bg-slate-100 overflow-hidden" role="meter" aria-label={`${r.name} occupancy`}
        aria-valuenow={r.occupancy_pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${tone.bar} transition-all duration-500`} style={{ width: `${Math.min(100, r.occupancy_pct)}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-slate-500 tabular-nums">{fmtNum(r.occupied)} of {fmtNum(r.capacity)} taken</p>
      {r.cameras.length === 0 ? (
        <p className="mt-2 text-[11px] text-amber-700">No camera linked to this row</p>
      ) : offline.length > 0 ? (
        <p className="mt-2 text-[11px] text-red-700 flex items-center gap-1"><Camera size={12} /> {offline.length} camera{offline.length > 1 ? "s" : ""} offline: count may be out of date</p>
      ) : null}
    </button>
  );
}

const EMPTY = { name: "", capacity: 20, sort_order: 0, is_active: true };

/** Rows management for the Parking Spaces page. */
export function RowsManager({ rows, reload }) {
  const { can } = useAuth();
  const toast = useToast();
  const [edit, setEdit] = useState(null);
  const [count, setCount] = useState(null);
  const [view, setView] = useState(null);
  const [busy, setBusy] = useState(false);
  const manage = can("occupancy.manage");

  const run = async (fn, msg, close) => {
    setBusy(true);
    try {
      await fn();
      toast(msg, "success");
      close?.();
      reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const saveRow = () => {
    const body = { name: edit.name, capacity: Number(edit.capacity), sort_order: Number(edit.sort_order) || 0, is_active: edit.is_active };
    run(() => (edit.id ? put(`/api/rows/${edit.id}`, body) : post("/api/rows", body)), edit.id ? "Row updated" : "Row added", () => setEdit(null));
  };

  const openView = async (r) => {
    setView({ row: r, vehicles: null });
    try {
      setView({ row: r, vehicles: await get(`/api/rows/${r.id}/vehicles`) });
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <Card title="Rows" action={manage && <Button size="sm" icon={Plus} onClick={() => setEdit({ ...EMPTY, sort_order: rows.length + 1 })}>Add row</Button>} bodyClass="p-0">
      <Table
        rows={rows}
        empty="No rows yet. Add a row, then add a camera at its entrance with Camera position set to that row."
        onRowClick={openView}
        columns={[
          { key: "name", label: "Row", render: (r) => <span className="font-medium text-slate-900">{r.name}{!r.is_active && <span className="ml-2 text-xs text-slate-400">(hidden)</span>}</span> },
          { key: "capacity", label: "Spaces", render: (r) => <span className="tabular-nums">{fmtNum(r.capacity)}</span> },
          { key: "occupied", label: "Taken", render: (r) => <span className="tabular-nums">{fmtNum(r.occupied)}</span> },
          { key: "available", label: "Free", render: (r) => <span className={`tabular-nums font-semibold ${rowTone(r).text}`}>{fmtNum(r.available)}</span> },
          { key: "cameras", label: "Cameras", render: (r) => r.cameras.length ? (
            <span className="text-xs">{r.cameras.map((c) => `${c.name} (${c.status.toLowerCase()})`).join(", ")}</span>
          ) : <span className="text-xs text-amber-700">none</span> },
          { key: "actions", label: "", render: (r) => (
            <div className="flex gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
              {can("transactions.manual") && <Button size="sm" variant="ghost" icon={SlidersHorizontal} title="Correct count" onClick={() => setCount({ row: r, count: r.occupied, reason: "" })} />}
              {manage && <Button size="sm" variant="ghost" icon={Pencil} title="Edit" onClick={() => setEdit({ ...r })} />}
              {manage && <Button size="sm" variant="ghost" icon={Trash2} title="Delete" onClick={() => window.confirm(`Delete ${r.name}? Its cameras become main gate cameras.`) && run(() => del(`/api/rows/${r.id}`), "Row deleted")} />}
            </div>
          ) },
        ]}
      />

      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? `Edit ${edit.name}` : "Add row"}
        footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={saveRow} loading={busy}>Save</Button></>}>
        {edit && (
          <div className="space-y-3">
            <Field label="Row name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="Row A" autoFocus /></Field>
            <Field label="Number of parking spaces"><Input type="number" min={0} value={edit.capacity} onChange={(e) => setEdit({ ...edit, capacity: e.target.value })} /></Field>
            <Field label="Display order" hint="Rows are shown from low to high"><Input type="number" value={edit.sort_order} onChange={(e) => setEdit({ ...edit, sort_order: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} /> Show on the dashboard</label>
          </div>
        )}
      </Modal>

      <Modal open={!!count} onClose={() => setCount(null)} title={`Correct the count of ${count?.row.name}`}
        footer={<><Button variant="secondary" onClick={() => setCount(null)}>Cancel</Button>
          <Button loading={busy} onClick={() => run(() => post(`/api/rows/${count.row.id}/count`, { count: Number(count.count), reason: count.reason }), "Count corrected", () => setCount(null))}>Save</Button></>}>
        {count && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Use this after a camera was offline or the count is wrong. Count the vehicles in the row and enter the number.</p>
            <Field label="Vehicles in the row now"><Input type="number" min={0} value={count.count} onChange={(e) => setCount({ ...count, count: e.target.value })} autoFocus /></Field>
            <Field label="Reason (saved in the audit log)"><Input value={count.reason} onChange={(e) => setCount({ ...count, reason: e.target.value })} placeholder="Camera was offline" /></Field>
          </div>
        )}
      </Modal>

      <Modal open={!!view} onClose={() => setView(null)} title={`Vehicles in ${view?.row.name}`}>
        {view && (view.vehicles === null ? <p className="text-sm text-slate-500">Loading…</p> : view.vehicles.length === 0 ? (
          <p className="text-sm text-slate-500">No vehicles in this row.</p>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
            {view.vehicles.map((v) => (
              <li key={v.id} className="py-2 flex items-center gap-3 text-sm">
                {v.plate_number ? <Plate value={v.plate_number} /> : <span className="italic text-slate-400">plate not read</span>}
                <SimBadge show={v.is_simulated} />
                <span className="ml-auto text-xs text-slate-500">since {fmtDateTime(v.entered_at)}</span>
              </li>
            ))}
          </ul>
        ))}
      </Modal>
    </Card>
  );
}
