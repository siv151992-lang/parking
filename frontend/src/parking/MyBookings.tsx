// My bookings (list) and one booking (QR code for the gate, change time, cancel, add to calendar).
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CalendarPlus, ChevronRight, Printer, XCircle } from "lucide-react";
import { useLiveRefresh } from "../lib/realtime";
import type { Booking, Page } from "./api";
import { STATUS_STYLE, VEHICLE_LABEL, fmtRange, hhmm, parkingApi, ymd } from "./api";
import { QrImage } from "./components";
import { useFetchT, useToastT } from "./hooks";
import { Badge, Button, Modal, Plate, Spinner } from "./ui";

const input = "block w-full rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600";

export function BookingStatusBadge({ status }: { status: Booking["status"] }) {
  const s = STATUS_STYLE[status];
  return <Badge color={s.color}>{s.label}</Badge>;
}

export default function MyBookings() {
  const [scope, setScope] = useState<"upcoming" | "past">("upcoming");
  const [page, setPage] = useState(1);
  const data = useFetchT<Page<Booking>>(() => parkingApi.myBookings(scope, page), [scope, page]);
  useLiveRefresh(["booking"], data.reload, 800);
  const items = data.data?.items || [];
  const pages = Math.max(1, Math.ceil((data.data?.total || 0) / 20));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-navy-900">My bookings</h1>
        <Link to="/park" className="text-sm font-semibold text-navy-700 hover:underline">+ New booking</Link>
      </div>
      <div className="inline-flex rounded-lg bg-slate-100 p-1" role="tablist">
        {(["upcoming", "past"] as const).map((s) => (
          <button key={s} type="button" role="tab" aria-selected={scope === s} onClick={() => { setScope(s); setPage(1); }}
            className={`px-4 py-1.5 rounded-md text-sm font-medium capitalize ${scope === s ? "bg-white shadow-sm text-navy-900" : "text-slate-600"}`}>{s}</button>
        ))}
      </div>
      {data.error && <p role="alert" className="text-sm text-red-600">{data.error.message}</p>}
      {data.loading && !data.data ? <Spinner /> : (
        <ul className="space-y-2.5">
          {items.map((b) => (
            <li key={b.id}>
              <Link to={`/park/bookings/${b.id}`} className="bg-white rounded-xl ring-1 ring-slate-200 hover:ring-navy-300 p-4 flex items-center gap-4">
                <div className="w-14 h-14 shrink-0 rounded-xl bg-navy-900 text-white flex flex-col items-center justify-center">
                  <span className="text-[10px] uppercase tracking-wide opacity-80">slot</span>
                  <span className="text-sm font-bold">{b.slot_code}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-900 truncate">{b.office_name}{b.visitor_name ? ` · visitor ${b.visitor_name}` : ""}</p>
                  <p className="text-sm text-slate-600">{fmtRange(b.start_at, b.end_at)}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{b.plate_number} · {b.code}</p>
                </div>
                <BookingStatusBadge status={b.status} />
                <ChevronRight size={18} className="text-slate-400 shrink-0 hidden sm:block" />
              </Link>
            </li>
          ))}
          {items.length === 0 && (
            <li className="bg-white rounded-xl ring-1 ring-slate-200 p-8 text-center text-sm text-slate-500">
              {scope === "upcoming" ? <>No upcoming bookings. <Link to="/park" className="font-semibold text-navy-700 underline">Book a slot</Link></> : "No past bookings."}
            </li>
          )}
        </ul>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>Page {page} of {pages}</span>
          <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}

/** An .ics file so the booking can be added to Outlook / Google Calendar. */
function downloadIcs(b: Booking) {
  const stamp = (iso: string) => new Date(iso).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const ics = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Office Parking//EN", "BEGIN:VEVENT",
    `UID:${b.code}@office-parking`, `DTSTAMP:${stamp(new Date().toISOString())}`,
    `DTSTART:${stamp(b.start_at)}`, `DTEND:${stamp(b.end_at)}`,
    `SUMMARY:Parking ${b.office_name} slot ${b.slot_code}`,
    `DESCRIPTION:Booking ${b.code}${b.plate_number ? ` for ${b.plate_number}` : ""}`,
    `LOCATION:${b.office_name}`, "END:VEVENT", "END:VCALENDAR",
  ].join("\r\n");
  const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `parking-${b.code}.ics`;
  a.click();
  URL.revokeObjectURL(url);
}

export function BookingDetail() {
  const { id } = useParams();
  const bid = Number(id);
  const data = useFetchT<Booking>(() => parkingApi.booking(bid), [bid]);
  useLiveRefresh(["booking"], data.reload, 500);
  const toast = useToastT();
  const nav = useNavigate();
  const [cancel, setCancel] = useState<{ reason: string } | null>(null);
  const [change, setChange] = useState<{ day: string; from: string; to: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (data.loading && !data.data) return <Spinner />;
  if (data.error) return <p role="alert" className="text-red-600">{data.error.message}</p>;
  const b = data.data as Booking;
  const active = b.status === "CONFIRMED" || b.status === "CHECKED_IN";

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast(msg, "success");
      setCancel(null);
      setChange(null);
      data.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <button type="button" onClick={() => nav("/park/bookings")} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-navy-900 print:hidden">
        <ArrowLeft size={16} /> My bookings
      </button>
      <div className="bg-white rounded-2xl ring-1 ring-slate-200 overflow-hidden">
        <div className="bg-navy-900 text-white px-5 py-4 flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-xs uppercase tracking-wide opacity-70">Parking booking</p>
            <p className="text-xl font-bold">{b.office_name} · slot {b.slot_code}</p>
          </div>
          <BookingStatusBadge status={b.status} />
        </div>
        <div className="p-5 grid sm:grid-cols-[auto_1fr] gap-6 items-start">
          <div className="flex flex-col items-center gap-2">
            {active && b.qr ? <QrImage text={b.qr} /> : <div className="w-[220px] h-[220px] rounded-lg bg-slate-100 flex items-center justify-center text-sm text-slate-500 text-center p-4">No QR code: this booking is {STATUS_STYLE[b.status].label.toLowerCase()}</div>}
            <p className="font-mono text-lg font-bold tracking-widest">{b.code}</p>
            {active && <p className="text-xs text-slate-500 text-center max-w-[220px]">Show this QR code (or tell the booking code) to security at the gate.</p>}
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-slate-500">When</dt><dd className="font-medium">{fmtRange(b.start_at, b.end_at)}</dd>
            <dt className="text-slate-500">Where</dt><dd>{b.office_name}{b.floor ? `, ${b.floor}` : ""}{b.zone ? `, zone ${b.zone}` : ""}, slot <b>{b.slot_code}</b></dd>
            <dt className="text-slate-500">Vehicle</dt><dd className="flex items-center gap-2"><Plate value={b.plate_number} /> {VEHICLE_LABEL[b.vehicle_type]}</dd>
            {b.visitor_name && <><dt className="text-slate-500">Visitor</dt><dd>{b.visitor_name}{b.visitor_phone ? ` · ${b.visitor_phone}` : ""}</dd></>}
            {b.checked_in_at && <><dt className="text-slate-500">Checked in</dt><dd>{new Date(b.checked_in_at).toLocaleString()}</dd></>}
            {b.checked_out_at && <><dt className="text-slate-500">Checked out</dt><dd>{new Date(b.checked_out_at).toLocaleString()}</dd></>}
            {b.status === "CANCELLED" && <><dt className="text-slate-500">Cancelled</dt><dd>{b.cancelled_at ? new Date(b.cancelled_at).toLocaleString() : ""}{b.cancel_reason ? ` · ${b.cancel_reason}` : ""}</dd></>}
            {b.status === "NO_SHOW" && <><dt className="text-slate-500">Released</dt><dd>Not checked in in time, so the slot was given back.</dd></>}
            {b.notes && <><dt className="text-slate-500">Note</dt><dd>{b.notes}</dd></>}
          </dl>
        </div>
        {active && (
          <div className="px-5 py-3 border-t border-slate-100 flex flex-wrap gap-2 print:hidden">
            <Button variant="secondary" onClick={() => setChange({ day: ymd(new Date(b.start_at)), from: hhmm(b.start_at), to: hhmm(b.end_at) })}>
              {b.status === "CHECKED_IN" ? "Extend" : "Change time"}
            </Button>
            <Button variant="secondary" icon={CalendarPlus} onClick={() => downloadIcs(b)}>Add to calendar</Button>
            <Button variant="secondary" icon={Printer} onClick={() => window.print()}>Print</Button>
            {b.status === "CONFIRMED" && <Button variant="danger" icon={XCircle} onClick={() => setCancel({ reason: "" })} className="sm:ml-auto">Cancel booking</Button>}
          </div>
        )}
      </div>

      <Modal open={!!cancel} onClose={() => setCancel(null)} title="Cancel this booking?"
        footer={<><Button variant="secondary" onClick={() => setCancel(null)}>Keep it</Button>
          <Button variant="danger" loading={busy} onClick={() => run(() => parkingApi.cancel(b.id, cancel?.reason || ""), "Booking cancelled")}>Cancel booking</Button></>}>
        {cancel && (
          <div className="space-y-3 text-sm">
            <p>Slot {b.slot_code} on {fmtRange(b.start_at, b.end_at)} becomes free for colleagues.</p>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Reason (optional)</span>
              <input className={input} value={cancel.reason} maxLength={255} onChange={(e) => setCancel({ reason: e.target.value })} /></label>
          </div>
        )}
      </Modal>

      <Modal open={!!change} onClose={() => setChange(null)} title={b.status === "CHECKED_IN" ? "Extend parking" : "Change time"}
        footer={<><Button variant="secondary" onClick={() => setChange(null)}>Close</Button>
          <Button loading={busy} disabled={!change || change.to <= change.from}
            onClick={() => change && run(() => parkingApi.change(b.id,
              b.status === "CHECKED_IN" ? b.start_at : new Date(`${change.day}T${change.from}`).toISOString(),
              new Date(`${change.day}T${change.to}`).toISOString()), "Booking updated")}>Save</Button></>}>
        {change && (
          <div className="grid grid-cols-3 gap-3 text-sm">
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Date</span>
              <input type="date" className={input} disabled={b.status === "CHECKED_IN"} value={change.day} onChange={(e) => setChange({ ...change, day: e.target.value })} /></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">From</span>
              <input type="time" step={900} className={input} disabled={b.status === "CHECKED_IN"} value={change.from} onChange={(e) => setChange({ ...change, from: e.target.value })} /></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">To</span>
              <input type="time" step={900} className={input} value={change.to} onChange={(e) => setChange({ ...change, to: e.target.value })} /></label>
            <p className="col-span-3 text-xs text-slate-500">You keep slot {b.slot_code}. If it is booked by someone else for part of the new time, the change is refused.</p>
          </div>
        )}
      </Modal>
    </div>
  );
}
