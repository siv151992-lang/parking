// Shared office-parking components: time window picker, office map, slot grid, QR code.
import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import QRCode from "qrcode";
import { Accessibility, BatteryCharging, UserRound } from "lucide-react";
import type { OfficeSummary, Slot } from "./api";
import { STATE_STYLE, nextQuarter, ymd } from "./api";

// ------------------------------------------------------------ time window
export interface Window { day: string; from: string; to: string }

export function defaultWindow(): Window {
  const now = new Date();
  const from = nextQuarter();
  if (from >= "17:00" || from < "06:00") {
    const t = new Date(now.getTime() + 86400000);
    return { day: ymd(t), from: "09:00", to: "18:00" };
  }
  return { day: ymd(now), from, to: "18:00" };
}

const fieldCls = "block w-full rounded-lg border-0 py-2 px-3 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600 bg-white";

export function WindowPicker({ value, onChange }: { value: Window; onChange: (w: Window) => void }) {
  const [{ today, tomorrow }] = useState(() => ({ today: ymd(new Date()), tomorrow: ymd(new Date(Date.now() + 86400000)) }));
  const quick = [
    { label: "Today", day: today, make: () => ({ day: today, from: nextQuarter() < "18:00" ? nextQuarter() : "09:00", to: "18:00" }) },
    { label: "Tomorrow", day: tomorrow, make: () => ({ day: tomorrow, from: "09:00", to: "18:00" }) },
  ];
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="block">
        <span className="block text-xs font-medium text-slate-600 mb-1">Date</span>
        <input type="date" className={fieldCls} min={today} value={value.day} onChange={(e) => onChange({ ...value, day: e.target.value })} />
      </label>
      <label className="block">
        <span className="block text-xs font-medium text-slate-600 mb-1">From</span>
        <input type="time" step={900} className={fieldCls} value={value.from} onChange={(e) => onChange({ ...value, from: e.target.value })} />
      </label>
      <label className="block">
        <span className="block text-xs font-medium text-slate-600 mb-1">To</span>
        <input type="time" step={900} className={fieldCls} value={value.to} onChange={(e) => onChange({ ...value, to: e.target.value })} />
      </label>
      <div className="flex gap-1.5 pb-0.5">
        {quick.map((q) => (
          <button key={q.label} type="button" onClick={() => onChange(q.make())}
            className={`px-3 py-1.5 rounded-full text-xs font-medium ring-1 ${value.day === q.day ? "bg-navy-900 text-white ring-navy-900" : "ring-slate-300 text-slate-600 hover:bg-slate-50"}`}>
            {q.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ map
/** OpenStreetMap with one marker per office, coloured by free slots. */
export function OfficeMap({ offices, selected, onSelect, className = "h-72" }:
  { offices: OfficeSummary[]; selected?: number | null; onSelect?: (id: number) => void; className?: string }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const located = useMemo(() => offices.filter((o) => o.latitude != null && o.longitude != null), [offices]);

  useEffect(() => {
    if (!el.current || map.current) return undefined;
    map.current = L.map(el.current, { scrollWheelZoom: false }).setView([20.6, 78.9], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!map.current || !layer.current) return;
    layer.current.clearLayers();
    for (const o of located) {
      const color = o.slots_free === 0 ? "#dc2626" : o.slots_free <= 3 ? "#f59e0b" : "#059669";
      const m = L.circleMarker([o.latitude as number, o.longitude as number], {
        radius: o.id === selected ? 13 : 10, color: "#0b2545", weight: o.id === selected ? 3 : 1.5, fillColor: color, fillOpacity: 0.9,
      });
      m.bindTooltip(`${o.name}: ${o.slots_free} free`, { direction: "top" });
      if (onSelect) m.on("click", () => onSelect(o.id));
      m.addTo(layer.current);
    }
    if (located.length === 1) map.current.setView([located[0].latitude as number, located[0].longitude as number], 14);
    else if (located.length > 1) map.current.fitBounds(L.latLngBounds(located.map((o) => [o.latitude as number, o.longitude as number])), { padding: [30, 30] });
  }, [located, selected, onSelect]);

  if (!located.length) return null;
  return <div ref={el} className={`w-full rounded-xl ring-1 ring-slate-200 z-0 ${className}`} role="region" aria-label="Map of offices" />;
}

/** Map to choose a location: click to set latitude / longitude. */
export function LocationPicker({ lat, lng, onPick }: { lat: number | null; lng: number | null; onPick: (lat: number, lng: number) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const pick = useRef(onPick);
  useEffect(() => {
    pick.current = onPick;
  });
  useEffect(() => {
    if (!el.current || map.current) return undefined;
    map.current = L.map(el.current).setView(lat != null && lng != null ? [lat, lng] : [20.6, 78.9], lat != null ? 15 : 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(map.current);
    map.current.on("click", (e: L.LeafletMouseEvent) => pick.current(Number(e.latlng.lat.toFixed(6)), Number(e.latlng.lng.toFixed(6))));
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!map.current) return;
    marker.current?.remove();
    if (lat != null && lng != null) marker.current = L.circleMarker([lat, lng], { radius: 9, color: "#0b2545", fillColor: "#059669", fillOpacity: 0.9 }).addTo(map.current);
  }, [lat, lng]);
  return <div ref={el} className="h-56 w-full rounded-lg ring-1 ring-slate-200 z-0" role="region" aria-label="Click the map to set the office location" />;
}

// ------------------------------------------------------------ slot grid
export function SlotLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-600">
      {(["AVAILABLE", "MINE", "BOOKED", "OCCUPIED", "ASSIGNED", "OUT_OF_SERVICE"] as const).map((s) => (
        <span key={s} className="flex items-center gap-1.5">
          <span className={`w-3.5 h-3.5 rounded ring-1 ${STATE_STYLE[s].cls.split(" hover")[0]}`} aria-hidden="true" />
          {STATE_STYLE[s].label}
        </span>
      ))}
      <span className="flex items-center gap-1"><BatteryCharging size={13} className="text-sky-600" /> EV charger</span>
      <span className="flex items-center gap-1"><Accessibility size={13} className="text-sky-600" /> Accessible</span>
      <span className="flex items-center gap-1"><UserRound size={13} className="text-violet-600" /> Visitors only</span>
    </div>
  );
}

/** Slots grouped by floor and zone. Free slots can be clicked when `onPick` is given. */
export function SlotGrid({ slots, selected, onPick, canPick, showDetails = false }: {
  slots: Slot[]; selected?: number | null; onPick?: (s: Slot) => void; canPick?: (s: Slot) => boolean; showDetails?: boolean;
}) {
  const groups = useMemo(() => {
    const g = new Map<string, { level: number; zones: Map<string, Slot[]> }>();
    for (const s of slots) {
      const f = s.floor || "—";
      if (!g.has(f)) g.set(f, { level: s.floor_level ?? 0, zones: new Map() });
      const zones = g.get(f)!.zones;
      const z = s.zone || "—";
      if (!zones.has(z)) zones.set(z, []);
      zones.get(z)!.push(s);
    }
    return [...g.entries()].sort((a, b) => a[1].level - b[1].level);
  }, [slots]);

  if (!slots.length) return <p className="text-sm text-slate-500">No slots set up for this office yet.</p>;
  return (
    <div className="space-y-5">
      {groups.map(([floor, { zones }]) => (
        <section key={floor}>
          <h3 className="text-sm font-semibold text-navy-900 mb-2">{floor}</h3>
          <div className="space-y-3">
            {[...zones.entries()].map(([zone, list]) => (
              <div key={zone}>
                <p className="text-xs font-medium text-slate-500 mb-1.5">Zone {zone}</p>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(4.25rem,1fr))] gap-1.5">
                  {list.map((s) => {
                    const state = s.state || "AVAILABLE";
                    const pickable = !!onPick && state === "AVAILABLE" && (!canPick || canPick(s));
                    const isSel = selected === s.id;
                    const who = s.booking ? `${s.booking.plate_number || ""} ${s.booking.visitor_name || s.booking.user_name || ""}`.trim() : "";
                    return (
                      <button key={s.id} type="button" disabled={!pickable} onClick={() => pickable && onPick?.(s)}
                        aria-pressed={isSel} title={`${s.code} · ${STATE_STYLE[state].label}${s.assigned_to ? ` · assigned to ${s.assigned_to}` : ""}${who ? ` · ${who}` : ""}`}
                        className={`relative h-14 rounded-lg ring-1 text-xs font-semibold flex flex-col items-center justify-center transition ${STATE_STYLE[state].cls}
                          ${pickable ? "cursor-pointer" : "cursor-default"} ${onPick && !pickable && state === "AVAILABLE" ? "opacity-40" : ""}
                          ${isSel ? "outline outline-[3px] outline-offset-2 outline-navy-900" : ""}`}>
                        <span>{s.code}</span>
                        <span className="flex gap-0.5 mt-0.5 opacity-90">
                          {s.is_ev && <BatteryCharging size={11} aria-label="EV charger" />}
                          {s.is_accessible && <Accessibility size={11} aria-label="Accessible" />}
                          {s.is_visitor && <UserRound size={11} aria-label="Visitors only" />}
                        </span>
                        {showDetails && who && <span className="absolute -bottom-0.5 inset-x-0.5 truncate text-[9px] font-normal opacity-90">{s.booking?.plate_number}</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ QR
export function QrImage({ text, size = 220 }: { text: string; size?: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    QRCode.toDataURL(text, { width: size, margin: 1, errorCorrectionLevel: "M" })
      .then((u) => alive && setSrc(u))
      .catch(() => alive && setSrc(null));
    return () => {
      alive = false;
    };
  }, [text, size]);
  return src ? <img src={src} width={size} height={size} alt="Booking QR code: show it at the gate" className="rounded-lg" />
    : <div style={{ width: size, height: size }} className="rounded-lg bg-slate-100 animate-pulse" />;
}
