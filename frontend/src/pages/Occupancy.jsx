import { useState } from "react";
import { AlertTriangle, CheckCircle2, Pencil, Scale } from "lucide-react";
import { get, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { fmtNum } from "../lib/format";
import { Button, Card, Field, Input, Modal, PageHeader, Spinner, StatCard, useFetch, useToast } from "../components/ui";

export function OccupancyBar({ c }) {
  const p = Math.min(100, c.occupancy_pct);
  const color = c.occupancy_pct >= 100 ? "bg-red-600" : c.occupancy_pct >= c.alert_threshold_pct ? "bg-amber-500" : "bg-navy-700";
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm mb-1.5">
        <span className="font-medium text-slate-700">{c.label}</span>
        <span className="tabular-nums text-slate-600">
          <span className="font-semibold text-slate-900">{fmtNum(c.occupied)}</span> / {fmtNum(c.total_capacity)}
          <span className="ml-2 text-xs text-slate-500">{c.occupancy_pct}%</span>
        </span>
      </div>
      <div className="relative h-2.5 rounded-full bg-slate-100 overflow-hidden" role="meter" aria-valuenow={c.occupancy_pct} aria-valuemin={0} aria-valuemax={100} aria-label={c.label}>
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${p}%` }} />
        <div className="absolute top-0 h-full w-0.5 bg-slate-400/70" style={{ left: `${c.alert_threshold_pct}%` }} title={`Alert threshold ${c.alert_threshold_pct}%`} />
      </div>
      <p className="text-[11px] text-slate-500 mt-1">{fmtNum(c.available)} available{c.occupancy_pct >= 100 ? " · FULL" : ""}</p>
    </div>
  );
}

export default function Occupancy() {
  const { can } = useAuth();
  const toast = useToast();
  const occ = useFetch(() => get("/api/occupancy"), []);
  const rec = useFetch(() => get("/api/occupancy/reconcile"), []);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  useLiveRefresh(["occupancy", "entry", "exit"], () => { occ.reload(); rec.reload(); }, 400);

  if (!occ.data) return <Spinner />;
  const o = occ.data;

  const save = async () => {
    setSaving(true);
    try {
      await put(`/api/occupancy/${edit.category}`, {
        total_capacity: Number(edit.total_capacity), alert_threshold_pct: Number(edit.alert_threshold_pct), label: edit.label, is_active: edit.is_active,
      });
      toast("Capacity updated", "success");
      setEdit(null);
      occ.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Parking Occupancy" subtitle="Occupied spaces are derived from active parking sessions, so the count can never drift or go negative" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total Capacity" value={fmtNum(o.total_capacity)} tone="slate" />
        <StatCard label="Occupied" value={fmtNum(o.occupied)} tone="navy" live />
        <StatCard label="Available" value={fmtNum(o.available)} tone="green" live />
        <StatCard label="Occupancy" value={`${o.occupancy_pct}%`} tone={o.occupancy_pct >= 90 ? "red" : "blue"} live />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {o.categories.map((c) => (
          <Card key={c.category} title={c.label}
            action={can("occupancy.manage") && <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setEdit({ ...c })}>Configure</Button>}>
            <OccupancyBar c={c} />
            <dl className="grid grid-cols-3 gap-2 mt-4 text-center">
              {[["Occupied", c.occupied], ["Available", c.available], ["Alert at", `${c.alert_threshold_pct}%`]].map(([k, v]) => (
                <div key={k} className="bg-slate-50 rounded-lg py-2">
                  <dt className="text-[11px] text-slate-500">{k}</dt>
                  <dd className="font-semibold text-slate-900 tabular-nums">{typeof v === "number" ? fmtNum(v) : v}</dd>
                </div>
              ))}
            </dl>
            {c.alert_state !== "NORMAL" && (
              <p className={`mt-3 text-xs font-medium flex items-center gap-1.5 ${c.alert_state === "FULL" ? "text-red-700" : "text-amber-700"}`}>
                <AlertTriangle size={14} /> {c.alert_state === "FULL" ? "Capacity reached" : "Above alert threshold"}
              </p>
            )}
          </Card>
        ))}
      </div>

      {rec.data && (
        <Card title={<span className="flex items-center gap-2"><Scale size={16} /> Count reconciliation</span>}>
          <div className="flex flex-col md:flex-row md:items-center gap-4">
            <div className={`flex items-center gap-2 font-semibold ${rec.data.is_consistent ? "text-emerald-700" : "text-red-700"}`}>
              {rec.data.is_consistent ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
              {rec.data.is_consistent ? "Counts are consistent" : `Discrepancy of ${rec.data.discrepancy}`}
            </div>
            <p className="text-sm text-slate-600 font-mono">
              {fmtNum(rec.data.total_valid_entries)} entries − {fmtNum(rec.data.total_counted_exits)} exits = {fmtNum(rec.data.expected_inside)} ={" "}
              {fmtNum(rec.data.active_sessions)} active sessions
            </p>
            {rec.data.pending_unmatched_exits > 0 && (
              <p className="text-xs text-amber-700 md:ml-auto">{rec.data.pending_unmatched_exits} unmatched exits awaiting review (not deducted)</p>
            )}
          </div>
        </Card>
      )}

      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Configure ${edit?.label}`}
        footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={save} loading={saving}>Save</Button></>}>
        {edit && (
          <div className="space-y-3">
            <Field label="Display name"><Input value={edit.label} onChange={(e) => setEdit({ ...edit, label: e.target.value })} /></Field>
            <Field label="Total capacity (spaces)"><Input type="number" min={0} value={edit.total_capacity} onChange={(e) => setEdit({ ...edit, total_capacity: e.target.value })} /></Field>
            <Field label="Alert threshold (%)" hint="A warning alert is raised when occupancy reaches this level; a critical alert at 100%.">
              <Input type="number" min={1} max={100} value={edit.alert_threshold_pct} onChange={(e) => setEdit({ ...edit, alert_threshold_pct: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} /> Include in total capacity</label>
          </div>
        )}
      </Modal>
    </div>
  );
}
