import { useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowDownToLine, ArrowUpFromLine, CameraOff, Plus } from "lucide-react";
import { get } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useEvent, useLiveRefresh } from "../lib/realtime";
import { fmtNum, fmtTime } from "../lib/format";
import { Badge, Card, Plate, SimBadge, Spinner, useFetch } from "../components/ui";
import { RowCard } from "./Rows";

export function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white shadow-lg ring-1 ring-slate-200 rounded-lg px-3 py-2 text-xs">
      <p className="font-semibold text-slate-800 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 text-slate-600">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: p.color }} />
          {p.name}: <span className="font-semibold text-slate-900 tabular-nums">{fmtNum(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

function BigNumber({ label, value, sub, tone = "text-navy-900" }) {
  return (
    <div className="bg-white rounded-xl ring-1 ring-slate-200 p-5">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`text-5xl font-bold tabular-nums mt-1 ${tone}`}>{value}</p>
      {sub && <p className="text-sm text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

const HIDDEN = new Set(["COOLDOWN", "ROW_IGNORED"]);

function movement(d) {
  if (d.status === "ROW_ENTRY") return { label: "into row", icon: ArrowDownToLine, cls: "text-emerald-700" };
  if (d.status === "ROW_EXIT") return { label: "left row", icon: ArrowUpFromLine, cls: "text-orange-700" };
  if (d.direction === "ENTRY") return { label: "came in", icon: ArrowDownToLine, cls: "text-emerald-700" };
  return { label: "went out", icon: ArrowUpFromLine, cls: "text-orange-700" };
}

export default function Dashboard() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const stats = useFetch(() => get("/api/dashboard/stats"), []);
  const recent = useFetch(() => get("/api/dashboard/recent-detections", { limit: 30 }), []);

  const refresh = useCallback(() => stats.reload(), [stats]);
  useLiveRefresh(["entry", "exit", "occupancy", "camera_status", "entry_updated", "exit_updated"], refresh, 500);
  useEvent("detection", (d) => {
    if (HIDDEN.has(d.status)) return;
    recent.setData((rows) => [d, ...(rows || []).filter((r) => r.id !== d.id)].slice(0, 30));
  });

  if (stats.loading && !stats.data) return <Spinner />;
  const s = stats.data;
  if (!s) return <p className="text-red-600">Failed to load: {stats.error?.message}</p>;
  const rows = s.occupancy.rows || [];
  const rowFree = rows.reduce((n, r) => n + r.available, 0);
  const rowTaken = rows.reduce((n, r) => n + r.occupied, 0);
  const latest = (recent.data || []).filter((d) => !HIDDEN.has(d.status)).slice(0, 8);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold text-navy-900">Parking now</h1>
        {s.simulated_cameras > 0 && <Badge color="violet" title="Some numbers come from simulated cameras">includes simulated cameras</Badge>}
      </div>

      {s.cameras_offline > 0 && (
        <Link to="/live" className="flex items-center gap-2 rounded-xl bg-red-50 text-red-800 ring-1 ring-red-200 px-4 py-3 text-sm font-medium">
          <CameraOff size={18} /> {s.cameras_offline} camera{s.cameras_offline > 1 ? "s are" : " is"} offline. Counts may be out of date.
        </Link>
      )}

      <div className="grid sm:grid-cols-3 gap-4">
        <BigNumber label="Free spaces" value={fmtNum(rows.length ? rowFree : s.available_spaces)}
          tone={(rows.length ? rowFree === 0 : s.available_spaces === 0) ? "text-red-600" : "text-emerald-600"}
          sub={rows.length ? `in ${rows.length} row${rows.length > 1 ? "s" : ""}` : `of ${fmtNum(s.total_capacity)} spaces`} />
        <BigNumber label="Vehicles inside" value={fmtNum(s.vehicles_inside)}
          sub={rows.length ? `${fmtNum(rowTaken)} parked in rows` : `${s.occupancy_pct}% full`} />
        <BigNumber label="Today" value={<span className="flex items-baseline gap-4 text-4xl">
          <span className="flex items-center gap-1 text-emerald-700"><ArrowDownToLine size={26} />{fmtNum(s.entries_today)}</span>
          <span className="flex items-center gap-1 text-orange-700"><ArrowUpFromLine size={26} />{fmtNum(s.exits_today)}</span>
        </span>} sub="vehicles in · out" />
      </div>

      <section>
        <h2 className="text-lg font-semibold text-navy-900 mb-3">Free spaces by row</h2>
        {rows.length ? (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
            {rows.map((r) => <RowCard key={r.id} r={r} onClick={can("occupancy.view") ? () => navigate("/occupancy") : undefined} />)}
          </div>
        ) : (
          <div className="bg-white rounded-xl ring-1 ring-slate-200 p-6 text-sm text-slate-600 flex flex-wrap items-center gap-3">
            No rows set up yet. Add your rows and their number of spaces, then put a camera at each row entrance.
            {can("occupancy.manage") && <Link to="/occupancy" className="inline-flex items-center gap-1 font-medium text-navy-700 hover:underline"><Plus size={16} /> Add rows</Link>}
          </div>
        )}
      </section>

      <Card title="Latest vehicles" bodyClass="p-0" action={<Link to="/history" className="text-xs font-medium text-navy-700 hover:underline">All vehicles</Link>}>
        <ul className="divide-y divide-slate-100">
          {latest.map((d) => {
            const m = movement(d);
            return (
              <li key={d.id} className="px-4 py-2.5 flex items-center gap-2 sm:gap-3 text-sm">
                <span className="w-28 sm:w-32 shrink-0">{d.plate_number ? <Plate value={d.plate_number} /> : <span className="italic text-slate-400">not read</span>}</span>
                <span className={`flex items-center gap-1 font-medium sm:w-24 shrink-0 whitespace-nowrap ${m.cls}`}><m.icon size={15} /> {m.label}</span>
                <span className="text-slate-500 truncate flex-1 min-w-0 hidden sm:block">{d.camera_name}</span>
                <span className="flex-1 sm:hidden" />
                <SimBadge show={d.is_simulated} />
                <span className="text-xs text-slate-500 tabular-nums whitespace-nowrap">{fmtTime(d.detected_at)}</span>
              </li>
            );
          })}
          {latest.length === 0 && <li className="px-4 py-6 text-sm text-slate-400 text-center">No vehicles yet</li>}
        </ul>
      </Card>
    </div>
  );
}
