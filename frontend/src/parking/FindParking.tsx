// Step 1: choose when, then an office (list + map) with free-slot counts for that time.
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Accessibility, BatteryCharging, ChevronRight, Clock, MapPin, UserRound } from "lucide-react";
import { Spinner } from "./ui";
import { useFetchT } from "./hooks";
import { useLiveRefresh } from "../lib/realtime";
import type { MyVehicle, OfficeSummary } from "./api";
import { VEHICLE_LABEL, atLocal, parkingApi } from "./api";
import type { Window } from "./components";
import { OfficeMap, WindowPicker, defaultWindow } from "./components";

export function windowFromParams(p: URLSearchParams): Window {
  const d = defaultWindow();
  return { day: p.get("day") || d.day, from: p.get("from") || d.from, to: p.get("to") || d.to };
}

export default function FindParking() {
  const [params, setParams] = useSearchParams();
  const [win, setWin] = useState<Window>(() => windowFromParams(params));
  const [vtype, setVtype] = useState(params.get("type") || "");
  const nav = useNavigate();
  const valid = win.to > win.from;
  const start = valid ? atLocal(win.day, win.from) : "";
  const end = valid ? atLocal(win.day, win.to) : "";
  const offices = useFetchT<OfficeSummary[]>(() => (valid ? parkingApi.offices(start, end, vtype) : Promise.resolve([])), [start, end, vtype]);
  const vehicles = useFetchT<MyVehicle[]>(() => parkingApi.myVehicles(), []);
  useLiveRefresh(["booking"], offices.reload, 800);

  const update = (w: Window) => {
    setWin(w);
    setParams({ day: w.day, from: w.from, to: w.to, ...(vtype ? { type: vtype } : {}) }, { replace: true });
  };
  const open = (id: number) => nav(`/park/office/${id}?day=${win.day}&from=${win.from}&to=${win.to}`);
  const list = offices.data || [];
  const myTypes = [...new Set((vehicles.data || []).map((v) => v.vehicle_type))];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-navy-900">Book a parking slot</h1>
        <p className="text-sm text-slate-500 mt-1">Choose when you need parking, then an office.</p>
      </div>

      {vehicles.data && vehicles.data.length === 0 && (
        <div className="rounded-xl bg-amber-50 text-amber-900 ring-1 ring-amber-200 px-4 py-3 text-sm flex flex-wrap items-center gap-2">
          Add your vehicle first, so security knows it is yours.
          <Link to="/park/vehicles" className="font-semibold underline">Add a vehicle</Link>
        </div>
      )}

      <div className="bg-white rounded-xl ring-1 ring-slate-200 p-4 space-y-3">
        <WindowPicker value={win} onChange={update} />
        {myTypes.length > 1 && (
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Vehicle type
            <select value={vtype} onChange={(e) => setVtype(e.target.value)} className="rounded-lg ring-1 ring-slate-300 py-1 px-2 text-sm">
              <option value="">All</option>
              {myTypes.map((t) => <option key={t} value={t}>{VEHICLE_LABEL[t]}</option>)}
            </select>
          </label>
        )}
        {!valid && <p role="alert" className="text-sm text-red-600">The end time must be after the start time.</p>}
      </div>

      {offices.error && <p role="alert" className="text-sm text-red-600">Could not load offices: {offices.error.message}</p>}
      {offices.loading && !offices.data ? <Spinner /> : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          <ul className="min-w-0 lg:col-span-3 space-y-3" aria-label="Offices">
            {list.map((o) => {
              const full = o.slots_free === 0;
              return (
                <li key={o.id}>
                  <button type="button" onClick={() => open(o.id)}
                    className="w-full text-left bg-white rounded-xl ring-1 ring-slate-200 hover:ring-navy-300 p-4 flex items-center gap-4 transition">
                    <div className={`w-16 h-16 shrink-0 rounded-xl flex flex-col items-center justify-center ${full ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
                      <span className="text-2xl font-bold tabular-nums leading-none">{o.slots_free}</span>
                      <span className="text-[11px] font-medium">free</span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-slate-900">{o.name}</p>
                      <p className="text-sm text-slate-500 flex items-center gap-1 truncate"><MapPin size={13} className="shrink-0" /> {[o.address, o.city].filter(Boolean).join(", ") || "—"}</p>
                      <p className="text-xs text-slate-500 mt-1 flex flex-wrap gap-x-3 gap-y-1">
                        <span className="flex items-center gap-1"><Clock size={12} /> {o.is_24h ? "Open 24 hours" : `${o.open_time}–${o.close_time}`}</span>
                        {o.ev_free > 0 && <span className="flex items-center gap-1 text-sky-700"><BatteryCharging size={12} /> {o.ev_free} EV</span>}
                        {o.accessible_free > 0 && <span className="flex items-center gap-1 text-sky-700"><Accessibility size={12} /> {o.accessible_free} accessible</span>}
                        {o.visitor_free > 0 && <span className="flex items-center gap-1 text-violet-700"><UserRound size={12} /> {o.visitor_free} visitor</span>}
                      </p>
                    </div>
                    <ChevronRight className="text-slate-400 shrink-0" size={20} />
                  </button>
                </li>
              );
            })}
            {list.length === 0 && valid && <li className="bg-white rounded-xl ring-1 ring-slate-200 p-8 text-center text-sm text-slate-500">No offices with parking are set up yet.</li>}
          </ul>
          <div className="min-w-0 lg:col-span-2">
            <div className="lg:sticky lg:top-20">
              <OfficeMap offices={list} onSelect={open} className="h-64 lg:h-[26rem]" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
