// Security desk (mobile-friendly): scan a booking QR code or type a booking code / vehicle number,
// check vehicles in and out, see today's arrivals and the live slot map of an office.
import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, CameraOff, LogIn, LogOut, Search } from "lucide-react";
import { useLiveRefresh } from "../lib/realtime";
import type { Availability, Booking, OfficeSummary, Page } from "./api";
import { STATUS_STYLE, VEHICLE_LABEL, fmtRange, parkingApi, ymd } from "./api";
import { SlotGrid, SlotLegend } from "./components";
import { useFetchT, useToastT } from "./hooks";
import { BookingStatusBadge } from "./MyBookings";
import { Badge, Button, Card, PageHeader, Plate, Spinner } from "./ui";

// Native QR scanning (Chrome / Edge / Android). Not in TypeScript's DOM types yet.
interface Detected { rawValue: string }
interface BarcodeDetectorLike { detect: (src: HTMLVideoElement) => Promise<Detected[]> }
declare global {
  interface Window { BarcodeDetector?: new (o: { formats: string[] }) => BarcodeDetectorLike }
}

function QrScanner({ onResult, onClose }: { onResult: (text: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const done = useRef(onResult);
  useEffect(() => {
    done.current = onResult;
  });
  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: number | undefined;
    let stopped = false;
    const start = async () => {
      if (!window.BarcodeDetector) {
        setError("This browser cannot scan QR codes. Use Chrome or Edge, or type the booking code.");
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("No camera access here. The page must be opened over HTTPS (or on this computer).");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      } catch {
        setError("The camera could not be opened. Allow camera access for this site.");
        return;
      }
      if (stopped || !video.current) return;
      video.current.srcObject = stream;
      await video.current.play().catch(() => {});
      const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      const tick = async () => {
        if (stopped || !video.current) return;
        try {
          const codes = await detector.detect(video.current);
          if (codes.length) {
            done.current(codes[0].rawValue);
            return;
          }
        } catch {
          /* frame not ready */
        }
        timer = window.setTimeout(tick, 250);
      };
      tick();
    };
    start();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  return (
    <div className="space-y-2">
      {error ? <p role="alert" className="text-sm text-amber-800 bg-amber-50 rounded-lg p-3">{error}</p> : (
        <video ref={video} muted playsInline className="w-full max-h-72 rounded-lg bg-black object-cover" aria-label="Camera: hold the QR code in view" />
      )}
      <Button variant="secondary" size="sm" icon={CameraOff} onClick={onClose}>Close camera</Button>
    </div>
  );
}

export default function SecurityDesk() {
  const toast = useToastT();
  const offices = useFetchT<OfficeSummary[]>(() => {
    const now = new Date();
    return parkingApi.offices(now.toISOString(), new Date(now.getTime() + 60000).toISOString());
  }, []);
  const [officeId, setOfficeId] = useState<number | "">(() => {
    try {
      return Number(localStorage.getItem("security.office")) || "";
    } catch {
      return "";
    }
  });
  const office = officeId || offices.data?.[0]?.id || "";
  const [text, setText] = useState("");
  const [found, setFound] = useState<Booking | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"CONFIRMED" | "CHECKED_IN" | "">("CONFIRMED");
  const [stamp, setStamp] = useState(() => new Date().toISOString());

  const today = useFetchT<Page<Booking> & { counts: Record<string, number> }>(
    () => (office ? parkingApi.allBookings({ office_id: office, day: ymd(new Date()), status: tab, page_size: 100 }) : Promise.resolve({ total: 0, items: [], counts: {} })),
    [office, tab]);
  const live = useFetchT<Availability | null>(
    () => (office ? parkingApi.availability(Number(office), stamp, new Date(new Date(stamp).getTime() + 60000).toISOString()) : Promise.resolve(null)),
    [office, stamp]);
  const refresh = useCallback(() => {
    today.reload();
    setStamp(new Date().toISOString());
  }, [today]);
  useLiveRefresh(["booking"], refresh, 700);

  const lookup = async (value: string) => {
    const v = value.trim();
    if (!v) return;
    setBusy(true);
    try {
      const b = await parkingApi.scan(v);
      setFound(b);
      setText("");
    } catch (e) {
      setFound(null);
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const act = async (b: Booking, action: "in" | "out") => {
    setBusy(true);
    try {
      const r = action === "in" ? await parkingApi.checkIn(b.id) : await parkingApi.checkOut(b.id);
      toast(action === "in" ? `${r.plate_number} checked in to slot ${r.slot_code}` : `${r.plate_number} checked out`, "success");
      setFound(found && found.id === b.id ? { ...r, verdict: { action: action === "in" ? "CHECK_OUT" : "NONE", ok: action === "in", message: action === "in" ? "Parked" : "Checked out" } } : found);
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const chooseOffice = (v: string) => {
    setOfficeId(Number(v) || "");
    try {
      localStorage.setItem("security.office", v);
    } catch {
      /* storage unavailable */
    }
  };
  const counts = today.data?.counts || {};

  return (
    <div className="space-y-5">
      <PageHeader title="Security Desk" subtitle="Scan the booking QR code, or type the booking code or vehicle number">
        <select aria-label="Office" value={office} onChange={(e) => chooseOffice(e.target.value)}
          className="rounded-lg ring-1 ring-slate-300 py-2 px-3 text-sm bg-white">
          {(offices.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </PageHeader>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start [&>*]:min-w-0">
        <Card title="Check a vehicle">
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); lookup(text); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} autoFocus placeholder="Booking code or vehicle number"
              aria-label="Booking code or vehicle number"
              className="flex-1 min-w-0 rounded-lg border-0 py-2.5 px-3 text-base ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600 uppercase" />
            <Button type="submit" icon={Search} loading={busy} disabled={!text.trim()}>Check</Button>
          </form>
          <div className="mt-3">
            {scanning ? <QrScanner onResult={(t) => { setScanning(false); lookup(t); }} onClose={() => setScanning(false)} />
              : <Button variant="secondary" icon={Camera} onClick={() => setScanning(true)}>Scan QR code</Button>}
          </div>
          {found && (
            <div className={`mt-4 rounded-xl ring-2 p-4 space-y-2 ${found.verdict?.ok ? "ring-emerald-500 bg-emerald-50" : "ring-red-400 bg-red-50"}`} aria-live="polite">
              <div className="flex flex-wrap items-center gap-2">
                <Plate value={found.plate_number} /><BookingStatusBadge status={found.status} />
                <span className="text-sm font-semibold">Slot {found.slot_code}</span>
              </div>
              <p className={`font-semibold ${found.verdict?.ok ? "text-emerald-800" : "text-red-800"}`}>{found.verdict?.message}</p>
              <p className="text-sm text-slate-700">{found.office_name} · {fmtRange(found.start_at, found.end_at)}</p>
              <p className="text-sm text-slate-700">{found.visitor_name ? `Visitor ${found.visitor_name} (host ${found.user_name})` : found.user_name} · {VEHICLE_LABEL[found.vehicle_type]} · {found.code}</p>
              {found.office_id !== Number(office) && <p className="text-sm font-semibold text-amber-800">Booked at another office: {found.office_name}</p>}
              <div className="flex gap-2 pt-1">
                {found.verdict?.action === "CHECK_IN" && <Button variant="success" icon={LogIn} loading={busy} onClick={() => act(found, "in")}>Check in</Button>}
                {found.verdict?.action === "CHECK_OUT" && <Button icon={LogOut} loading={busy} onClick={() => act(found, "out")}>Check out</Button>}
                <Button variant="ghost" onClick={() => setFound(null)}>Clear</Button>
              </div>
            </div>
          )}
        </Card>

        <Card title="Today" bodyClass="p-0" action={
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5 text-xs" role="tablist">
            {([["CONFIRMED", "Arriving"], ["CHECKED_IN", "Parked"], ["", "All"]] as const).map(([v, l]) => (
              <button key={l} type="button" role="tab" aria-selected={tab === v} onClick={() => setTab(v)}
                className={`px-2.5 py-1 rounded-md font-medium ${tab === v ? "bg-white shadow-sm text-navy-900" : "text-slate-600"}`}>
                {l}{v ? ` ${counts[v] || 0}` : ""}
              </button>
            ))}
          </div>}>
          {today.loading && !today.data ? <Spinner /> : (
            <ul className="divide-y divide-slate-100 max-h-[28rem] overflow-y-auto">
              {(today.data?.items || []).map((b) => (
                <li key={b.id} className="px-4 py-2.5 flex items-center gap-3 text-sm">
                  <span className="w-12 font-semibold text-navy-900">{b.slot_code}</span>
                  <div className="min-w-0 flex-1">
                    <Plate value={b.plate_number} />
                    <p className="text-xs text-slate-500 truncate">{b.visitor_name ? `Visitor ${b.visitor_name}` : b.user_name} · {fmtRange(b.start_at, b.end_at)}</p>
                  </div>
                  {b.status === "CONFIRMED" && <Button size="sm" variant="success" disabled={busy} onClick={() => act(b, "in")}>Check in</Button>}
                  {b.status === "CHECKED_IN" && <Button size="sm" disabled={busy} onClick={() => act(b, "out")}>Check out</Button>}
                  {!["CONFIRMED", "CHECKED_IN"].includes(b.status) && <Badge color={STATUS_STYLE[b.status].color}>{STATUS_STYLE[b.status].label}</Badge>}
                </li>
              ))}
              {today.data?.items.length === 0 && <li className="px-4 py-8 text-center text-sm text-slate-500">Nothing here today</li>}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Slots right now">
        <div className="space-y-3">
          <SlotLegend />
          {live.data ? <SlotGrid slots={live.data.slots} showDetails /> : <Spinner />}
        </div>
      </Card>
    </div>
  );
}
