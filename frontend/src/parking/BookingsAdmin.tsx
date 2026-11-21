// All slot bookings for a day (security and managers): filter, search, check in / out, cancel.
import { useState } from "react";
import { Search, XCircle } from "lucide-react";
import { useLiveRefresh } from "../lib/realtime";
import type { Booking, OfficeSummary, Page } from "./api";
import { STATUS_STYLE, VEHICLE_LABEL, fmtRange, parkingApi, ymd } from "./api";
import { useAuthT } from "./auth";
import { useFetchT, useToastT } from "./hooks";
import { BookingStatusBadge } from "./MyBookings";
import { Button, Card, Modal, PageHeader, Plate, Spinner } from "./ui";

const field = "rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600 bg-white";
const PAGE = 25;

export default function BookingsAdmin() {
  const { can } = useAuthT();
  const toast = useToastT();
  const [f, setF] = useState(() => ({ day: ymd(new Date()), office_id: "" as number | "", status: "", q: "", page: 1 }));
  const offices = useFetchT<OfficeSummary[]>(() => {
    const now = new Date();
    return parkingApi.offices(now.toISOString(), new Date(now.getTime() + 60000).toISOString(), "", true);
  }, []);
  const data = useFetchT<Page<Booking> & { counts: Record<string, number> }>(
    () => parkingApi.allBookings({ ...f, page_size: PAGE }), [f.day, f.office_id, f.status, f.q, f.page]);
  useLiveRefresh(["booking"], data.reload, 800);
  const [cancel, setCancel] = useState<{ b: Booking; reason: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast(msg, "success");
      setCancel(null);
      data.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const counts = data.data?.counts || {};
  const pages = Math.max(1, Math.ceil((data.data?.total || 0) / PAGE));

  return (
    <div className="space-y-5">
      <PageHeader title="Slot Bookings" subtitle="Reservations of office parking slots, by day" />
      <div className="flex flex-wrap gap-2">
        {(["", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"] as const).map((s) => (
          <button key={s || "all"} type="button" onClick={() => setF({ ...f, status: s, page: 1 })} aria-pressed={f.status === s}
            className={`px-3 py-1.5 rounded-full text-xs font-medium ring-1 ${f.status === s ? "bg-navy-900 text-white ring-navy-900" : "bg-white ring-slate-300 text-slate-600"}`}>
            {s ? STATUS_STYLE[s].label : "All"} <span className="tabular-nums opacity-80">{s ? counts[s] || 0 : Object.values(counts).reduce((a, b) => a + b, 0)}</span>
          </button>
        ))}
      </div>
      <Card bodyClass="p-0">
        <div className="flex flex-wrap gap-2 p-3 border-b border-slate-100">
          <input type="date" aria-label="Day" className={field} value={f.day} onChange={(e) => setF({ ...f, day: e.target.value, page: 1 })} />
          <select aria-label="Office" className={field} value={f.office_id} onChange={(e) => setF({ ...f, office_id: Number(e.target.value) || "", page: 1 })}>
            <option value="">All offices</option>
            {(offices.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <div className="relative flex-1 min-w-[12rem]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input aria-label="Search" placeholder="Name, vehicle, slot or booking code" className={`${field} w-full pl-8`} value={f.q}
              onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} />
          </div>
        </div>
        {data.loading && !data.data ? <Spinner /> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead><tr className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Time</th><th className="px-3 py-2">Office / slot</th><th className="px-3 py-2">Person</th>
                <th className="px-3 py-2">Vehicle</th><th className="px-3 py-2">Status</th><th className="px-3 py-2" />
              </tr></thead>
              <tbody className="divide-y divide-slate-100">
                {(data.data?.items || []).map((b) => (
                  <tr key={b.id} className="hover:bg-slate-50/60">
                    <td className="px-3 py-2 whitespace-nowrap">{fmtRange(b.start_at, b.end_at)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{b.office_name} · <b>{b.slot_code}</b></td>
                    <td className="px-3 py-2">{b.visitor_name ? <>{b.visitor_name} <span className="text-xs text-slate-500">(visitor of {b.user_name})</span></> : b.user_name}</td>
                    <td className="px-3 py-2 whitespace-nowrap"><Plate value={b.plate_number} /> <span className="text-xs text-slate-500">{VEHICLE_LABEL[b.vehicle_type]}</span></td>
                    <td className="px-3 py-2"><BookingStatusBadge status={b.status} /></td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1 justify-end whitespace-nowrap">
                        {b.status === "CONFIRMED" && <Button size="sm" variant="success" disabled={busy} onClick={() => run(() => parkingApi.checkIn(b.id), `${b.plate_number} checked in`)}>Check in</Button>}
                        {b.status === "CHECKED_IN" && <Button size="sm" disabled={busy} onClick={() => run(() => parkingApi.checkOut(b.id), `${b.plate_number} checked out`)}>Check out</Button>}
                        {b.status === "CONFIRMED" && can("bookings.manage") && <Button size="sm" variant="ghost" icon={XCircle} onClick={() => setCancel({ b, reason: "" })}>Cancel</Button>}
                      </div>
                    </td>
                  </tr>
                ))}
                {data.data?.items.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">No bookings for this day</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-end gap-3 p-3 border-t border-slate-100 text-sm">
            <Button variant="secondary" size="sm" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>Previous</Button>
            <span>Page {f.page} of {pages}</span>
            <Button variant="secondary" size="sm" disabled={f.page >= pages} onClick={() => setF({ ...f, page: f.page + 1 })}>Next</Button>
          </div>
        )}
      </Card>
      <Modal open={!!cancel} onClose={() => setCancel(null)} title={`Cancel booking ${cancel?.b.code ?? ""}?`}
        footer={<><Button variant="secondary" onClick={() => setCancel(null)}>Keep</Button>
          <Button variant="danger" loading={busy} disabled={!cancel || cancel.reason.trim().length < 3}
            onClick={() => cancel && run(() => parkingApi.cancel(cancel.b.id, cancel.reason), "Booking cancelled")}>Cancel booking</Button></>}>
        {cancel && (
          <label className="block text-sm"><span className="block text-xs font-medium text-slate-600 mb-1">Reason (the person sees it)</span>
            <input className={`${field} w-full`} value={cancel.reason} maxLength={255} autoFocus onChange={(e) => setCancel({ ...cancel, reason: e.target.value })} /></label>
        )}
      </Modal>
    </div>
  );
}
