// Step 2: see the office's slots for the chosen time, pick one (or let the system choose), confirm.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Clock, MapPin } from "lucide-react";
import { Button, Spinner } from "./ui";
import { useLiveRefresh } from "../lib/realtime";
import type { Availability, MyVehicle, Slot, VehicleType } from "./api";
import { VEHICLE_LABEL, atLocal, parkingApi } from "./api";
import type { Window } from "./components";
import { SlotGrid, SlotLegend, WindowPicker } from "./components";
import { windowFromParams } from "./FindParking";
import { useFetchT, useToastT } from "./hooks";

const input = "block w-full rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600";

export default function OfficeBooking() {
  const { id } = useParams();
  const officeId = Number(id);
  const [params, setParams] = useSearchParams();
  const [win, setWin] = useState<Window>(() => windowFromParams(params));
  const valid = win.to > win.from;
  const start = valid ? atLocal(win.day, win.from) : "";
  const end = valid ? atLocal(win.day, win.to) : "";
  const avail = useFetchT<Availability | null>(() => (valid ? parkingApi.availability(officeId, start, end) : Promise.resolve(null)), [officeId, start, end]);
  const vehicles = useFetchT<MyVehicle[]>(() => parkingApi.myVehicles(), []);
  useLiveRefresh(["booking"], avail.reload, 600);
  const toast = useToastT();
  const nav = useNavigate();

  const [forVisitor, setForVisitor] = useState(false);
  const [vehicleId, setVehicleId] = useState<number | null>(null);
  const [visitor, setVisitor] = useState({ name: "", plate_number: "", vehicle_type: "CAR" as VehicleType, phone: "" });
  const [slot, setSlot] = useState<Slot | null>(null);
  const [prefs, setPrefs] = useState({ ev: false, accessible: false });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const myVehicles = vehicles.data || [];
  const chosenVehicle = myVehicles.find((v) => v.id === vehicleId) || myVehicles[0];  // first vehicle unless another is chosen
  const vtype: VehicleType | undefined = forVisitor ? visitor.vehicle_type : chosenVehicle?.vehicle_type;
  const canPick = (s: Slot) => (!vtype || s.vehicle_type === vtype) && (forVisitor || !s.is_visitor);
  const selected = slot && canPick(slot) && avail.data?.slots.find((s) => s.id === slot.id)?.state === "AVAILABLE" ? slot : null;
  const ready = valid && (forVisitor ? visitor.name.trim().length > 1 && visitor.plate_number.trim().length > 2 : !!chosenVehicle);

  const updateWin = (w: Window) => {
    setWin(w);
    setParams({ day: w.day, from: w.from, to: w.to }, { replace: true });
  };

  const submit = async () => {
    setBusy(true);
    try {
      const b = await parkingApi.book({
        office_id: officeId, start_at: start, end_at: end, slot_id: selected?.id ?? null,
        vehicle_id: forVisitor ? null : chosenVehicle?.id ?? null,
        visitor: forVisitor ? { ...visitor, name: visitor.name.trim(), plate_number: visitor.plate_number.trim() } : null,
        prefer_ev: prefs.ev, prefer_accessible: prefs.accessible, notes,
      });
      toast(`Booked slot ${b.slot_code}`, "success");
      nav(`/park/bookings/${b.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      avail.reload();
    } finally {
      setBusy(false);
    }
  };

  if (avail.loading && !avail.data) return <Spinner />;
  if (avail.error) return <p role="alert" className="text-red-600">{avail.error.message}</p>;
  const office = avail.data?.office;
  const slots = avail.data?.slots || [];
  const free = slots.filter((s) => s.state === "AVAILABLE" && canPick(s)).length;

  return (
    <div className="space-y-5">
      <Link to={`/park?day=${win.day}&from=${win.from}&to=${win.to}`} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-navy-900">
        <ArrowLeft size={16} /> All offices
      </Link>
      {office && (
        <div>
          <h1 className="text-2xl font-bold text-navy-900">{office.name}</h1>
          <p className="text-sm text-slate-500 flex flex-wrap gap-x-4 gap-y-1 mt-1">
            <span className="flex items-center gap-1"><MapPin size={14} /> {[office.address, office.city].filter(Boolean).join(", ") || "—"}</span>
            <span className="flex items-center gap-1"><Clock size={14} /> {office.is_24h ? "Open 24 hours" : `Parking open ${office.open_time}–${office.close_time}`}</span>
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        <section className="min-w-0 lg:col-span-2 bg-white rounded-xl ring-1 ring-slate-200 p-4 space-y-4" aria-label="Slots">
          <WindowPicker value={win} onChange={updateWin} />
          {!valid && <p role="alert" className="text-sm text-red-600">The end time must be after the start time.</p>}
          <SlotLegend />
          <p className="text-sm text-slate-600"><b className="text-emerald-700">{free}</b> free slot{free === 1 ? "" : "s"} for {vtype ? VEHICLE_LABEL[vtype].toLowerCase() : "you"}. Click one to choose it, or book and get one automatically.</p>
          <SlotGrid slots={slots} selected={selected?.id} onPick={(s) => setSlot(selected?.id === s.id ? null : s)} canPick={canPick} />
        </section>

        <aside className="min-w-0 bg-white rounded-xl ring-1 ring-slate-200 p-4 space-y-4 lg:sticky lg:top-20" aria-label="Your booking">
          <h2 className="font-semibold text-navy-900">Your booking</h2>
          <div className="inline-flex rounded-lg bg-slate-100 p-1 text-sm" role="tablist">
            {[["Me", false], ["A visitor", true]].map(([label, v]) => (
              <button key={String(label)} type="button" role="tab" aria-selected={forVisitor === v} onClick={() => { setForVisitor(v as boolean); setSlot(null); }}
                className={`px-3 py-1 rounded-md font-medium ${forVisitor === v ? "bg-white shadow-sm text-navy-900" : "text-slate-600"}`}>{label as string}</button>
            ))}
          </div>

          {!forVisitor ? (
            myVehicles.length === 0 ? (
              <p className="text-sm text-amber-800 bg-amber-50 rounded-lg p-3">You have no vehicle yet. <Link to="/park/vehicles" className="font-semibold underline">Add one</Link> first.</p>
            ) : (
              <label className="block">
                <span className="block text-xs font-medium text-slate-600 mb-1">Vehicle</span>
                <select className={input} value={chosenVehicle?.id ?? ""} onChange={(e) => { setVehicleId(Number(e.target.value)); setSlot(null); }}>
                  {myVehicles.map((v) => <option key={v.id} value={v.id}>{v.plate_number} · {VEHICLE_LABEL[v.vehicle_type]}</option>)}
                </select>
              </label>
            )
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 block"><span className="block text-xs font-medium text-slate-600 mb-1">Visitor name</span>
                <input className={input} value={visitor.name} onChange={(e) => setVisitor({ ...visitor, name: e.target.value })} /></label>
              <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Vehicle number</span>
                <input className={`${input} uppercase`} value={visitor.plate_number} onChange={(e) => setVisitor({ ...visitor, plate_number: e.target.value.toUpperCase() })} /></label>
              <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Type</span>
                <select className={input} value={visitor.vehicle_type} onChange={(e) => { setVisitor({ ...visitor, vehicle_type: e.target.value as VehicleType }); setSlot(null); }}>
                  {(Object.keys(VEHICLE_LABEL) as VehicleType[]).map((t) => <option key={t} value={t}>{VEHICLE_LABEL[t]}</option>)}
                </select></label>
              <label className="col-span-2 block"><span className="block text-xs font-medium text-slate-600 mb-1">Visitor phone (optional)</span>
                <input className={input} type="tel" value={visitor.phone} onChange={(e) => setVisitor({ ...visitor, phone: e.target.value })} /></label>
            </div>
          )}

          {selected ? (
            <p className="text-sm">Slot <b>{selected.code}</b> · {selected.floor}, zone {selected.zone}
              <button type="button" className="ml-2 text-xs text-slate-500 underline" onClick={() => setSlot(null)}>choose automatically</button></p>
          ) : (
            <fieldset className="space-y-1.5 text-sm">
              <legend className="text-xs font-medium text-slate-600 mb-1">The system picks a free slot{prefs.ev || prefs.accessible ? "" : " for you"}</legend>
              <label className="flex items-center gap-2"><input type="checkbox" checked={prefs.ev} onChange={(e) => setPrefs({ ...prefs, ev: e.target.checked })} /> I need an EV charger</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={prefs.accessible} onChange={(e) => setPrefs({ ...prefs, accessible: e.target.checked })} /> I need an accessible slot</label>
            </fieldset>
          )}
          <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Note for security (optional)</span>
            <input className={input} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
          <Button className="w-full" onClick={submit} loading={busy} disabled={!ready || free === 0}>
            {free === 0 ? "No free slot for this time" : selected ? `Book slot ${selected.code}` : "Book a free slot"}
          </Button>
        </aside>
      </div>
    </div>
  );
}
