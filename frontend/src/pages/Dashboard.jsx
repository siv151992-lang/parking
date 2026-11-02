import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDownToLine, ArrowUpFromLine, Bike, Camera, CameraOff, Car, CircleParking, Gauge, ParkingSquare, ShieldAlert, Truck } from "lucide-react";
import { get } from "../lib/api";
import { useEvent, useLiveRefresh } from "../lib/realtime";
import { fmtNum, fmtTime, sinceNow, VEHICLE_TYPES } from "../lib/format";
import { Badge, Card, PageHeader, Plate, SERIES, SimBadge, Spinner, StatCard, StatusBadge, Table, Thumb, useFetch } from "../components/ui";
import { authUrl } from "../lib/api";
import { OccupancyBar } from "./Occupancy";

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

export default function Dashboard() {
  const stats = useFetch(() => get("/api/dashboard/stats"), []);
  const hourly = useFetch(() => get("/api/dashboard/hourly"), []);
  const cams = useFetch(() => get("/api/cameras").catch(() => []), []);
  const recent = useFetch(() => get("/api/dashboard/recent-detections", { limit: 15 }), []);
  const [flash, setFlash] = useState(null);

  const refreshStats = useCallback(() => {
    stats.reload();
    hourly.reload();
  }, [stats, hourly]);
  useLiveRefresh(["entry", "exit", "occupancy", "camera_status", "alert", "entry_updated", "exit_updated"], refreshStats, 500);
  useLiveRefresh(["camera_status"], cams.reload, 300);
  useEvent("detection", (d) => {
    if (d.status === "COOLDOWN") return;
    recent.setData((rows) => [d, ...(rows || []).filter((r) => r.id !== d.id)].slice(0, 15));
    setFlash(d.id);
  });

  if (stats.loading && !stats.data) return <Spinner />;
  const s = stats.data;
  if (!s) return <p className="text-red-600">Failed to load dashboard: {stats.error?.message}</p>;

  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" subtitle="Live parking status from ANPR cameras and the transaction database">
        {s.simulated_cameras > 0 && (
          <Badge color="violet" title="Some counts come from simulated cameras">
            {s.simulated_cameras} simulated camera{s.simulated_cameras > 1 ? "s" : ""} · {fmtNum(s.simulated_entries_today)} simulated entries today
          </Badge>
        )}
      </PageHeader>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Total Entry Today" value={fmtNum(s.entries_today)} icon={ArrowDownToLine} tone="blue" live />
        <StatCard label="Total Exit Today" value={fmtNum(s.exits_today)} icon={ArrowUpFromLine} tone="orange" live sub={s.unmatched_exits_today ? `${s.unmatched_exits_today} unmatched` : undefined} />
        <StatCard label="Vehicles Inside" value={fmtNum(s.vehicles_inside)} icon={CircleParking} tone="navy" live />
        <StatCard label="Total Capacity" value={fmtNum(s.total_capacity)} icon={ParkingSquare} tone="slate" />
        <StatCard label="Available Spaces" value={fmtNum(s.available_spaces)} icon={ParkingSquare} tone="green" live />
        <StatCard label="Occupancy" value={`${s.occupancy_pct}%`} icon={Gauge} tone={s.occupancy_pct >= 90 ? "red" : s.occupancy_pct >= 75 ? "orange" : "green"} live />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Cars Today" value={fmtNum(s.cars_today)} icon={Car} tone="slate" sub="entries" />
        <StatCard label="Two-Wheelers Today" value={fmtNum(s.two_wheelers_today)} icon={Bike} tone="slate" sub="entries" />
        <StatCard label="Commercial Today" value={fmtNum(s.commercial_today)} icon={Truck} tone="slate" sub="entries" />
        <StatCard label="Active Cameras" value={`${s.cameras_online}/${s.cameras_total}`} icon={Camera} tone="green" sub={s.cameras_disabled ? `${s.cameras_disabled} disabled` : "online"} />
        <StatCard label="Offline Cameras" value={fmtNum(s.cameras_offline)} icon={CameraOff} tone={s.cameras_offline ? "red" : "slate"} />
        <StatCard label="Duplicates Blocked" value={fmtNum(s.duplicates_blocked_today)} icon={ShieldAlert} tone="violet" sub={`of ${fmtNum(s.detections_today)} detections`} />
      </div>

      <div className="grid xl:grid-cols-3 gap-5">
        <Card title="Today's traffic by hour" className="xl:col-span-2">
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={hourly.data || []} barGap={2} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="hour" tickLine={false} axisLine={false} interval={2} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
                <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="entries" name="Entries" fill={SERIES.entries} radius={[4, 4, 0, 0]} maxBarSize={14} />
                <Bar dataKey="exits" name="Exits" fill={SERIES.exits} radius={[4, 4, 0, 0]} maxBarSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Occupancy by category" action={<Link to="/occupancy" className="text-xs font-medium text-navy-700 hover:underline">Manage</Link>}>
          <div className="space-y-4">
            {s.occupancy.categories.map((c) => (
              <OccupancyBar key={c.category} c={c} />
            ))}
          </div>
        </Card>
      </div>

      <div className="grid xl:grid-cols-3 gap-5">
        <Card title="Recent number plate detections" className="xl:col-span-2" bodyClass="p-0"
          action={<Link to="/history" className="text-xs font-medium text-navy-700 hover:underline">All history</Link>}>
          <Table
            rows={recent.data || []}
            columns={[
              { key: "img", label: "Plate", render: (d) => <Thumb src={authUrl(d.plate_image)} alt="plate" className="w-20 h-7" /> },
              { key: "plate_number", label: "Reg. No.", render: (d) => <span className="flex items-center gap-1.5"><Plate value={d.plate_number} /><SimBadge show={d.is_simulated} /></span> },
              { key: "direction", label: "Dir", render: (d) => <StatusBadge status={d.direction} /> },
              { key: "vehicle_type", label: "Type", render: (d) => VEHICLE_TYPES[d.vehicle_type] },
              { key: "camera_name", label: "Camera" },
              { key: "plate_confidence", label: "Conf.", render: (d) => <span className="tabular-nums">{Math.round(d.plate_confidence * 100)}%</span> },
              { key: "status", label: "Result", render: (d) => <StatusBadge status={d.status} /> },
              { key: "detected_at", label: "Time", render: (d) => <span className={d.id === flash ? "row-flash px-1 rounded" : ""}>{fmtTime(d.detected_at)}</span> },
            ]}
            empty="No detections yet"
          />
        </Card>

        <Card title="ANPR cameras" bodyClass="p-0" action={<Link to="/live" className="text-xs font-medium text-navy-700 hover:underline">Live view</Link>}>
          <ul className="divide-y divide-slate-100">
            {(cams.data || []).map((c) => (
              <li key={c.id} className="px-4 py-3 flex items-center gap-3">
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${c.status === "ONLINE" ? "bg-emerald-500" : c.status === "DISABLED" ? "bg-slate-300" : "bg-red-500"}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800 truncate flex items-center gap-1.5">{c.name} <SimBadge show={c.is_simulated} /></p>
                  <p className="text-xs text-slate-500">{c.camera_code} · {c.direction} · last detection {sinceNow(c.last_detection_at)}</p>
                </div>
                <StatusBadge status={c.status} />
              </li>
            ))}
            {cams.data?.length === 0 && <li className="px-4 py-6 text-sm text-slate-400 text-center">No cameras configured</li>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
