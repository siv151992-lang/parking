// Office parking: types and API calls (backend: app/api/office_parking.py).
import { del, get, post, put } from "../lib/api";

export type VehicleType = "CAR" | "TWO_WHEELER" | "COMMERCIAL";
export type SlotState = "AVAILABLE" | "BOOKED" | "OCCUPIED" | "MINE" | "ASSIGNED" | "OUT_OF_SERVICE";
export type BookingStatus = "CONFIRMED" | "CHECKED_IN" | "COMPLETED" | "CANCELLED" | "NO_SHOW";

export interface Zone { id: number; name: string }
export interface Floor { id: number; name: string; level: number; zones: Zone[] }
export interface Office {
  id: number; name: string; city: string; address: string;
  latitude: number | null; longitude: number | null;
  is_24h: boolean; open_time: string; close_time: string; is_active: boolean; notes: string;
  floors: Floor[];
}
export interface OfficeSummary extends Office {
  slots_total: number; slots_free: number; ev_free: number; accessible_free: number; visitor_free: number;
}
export interface Slot {
  id: number; office_id: number; zone_id: number; code: string; zone: string | null; floor: string | null;
  floor_level: number | null; vehicle_type: VehicleType; is_ev: boolean; is_accessible: boolean; is_visitor: boolean;
  status: "ACTIVE" | "OUT_OF_SERVICE"; assigned_user_id: number | null; assigned_to: string | null;
  state?: SlotState;
  booking?: { id: number; code: string; plate_number: string | null; user_name: string | null; visitor_name: string | null; end_at: string };
}
export interface Availability { office: Office; start: string; end: string; slots: Slot[] }
export interface MyVehicle { id: number; plate_number: string; vehicle_type: VehicleType; notes: string }
export interface Booking {
  id: number; code: string; status: BookingStatus; office_id: number; office_name: string | null;
  slot_id: number | null; slot_code: string; floor: string | null; zone: string | null;
  user_id: number | null; user_name: string | null; plate_number: string | null; vehicle_type: VehicleType;
  visitor_name: string | null; visitor_phone: string | null; start_at: string; end_at: string;
  checked_in_at: string | null; checked_out_at: string | null; cancelled_at: string | null; cancel_reason: string;
  notes: string; created_at: string; qr?: string;
  verdict?: { action: "CHECK_IN" | "CHECK_OUT" | "NONE"; ok: boolean; message: string };
}
export interface Page<T> { total: number; items: T[] }
export interface Person { id: number; name: string; username: string; role: string; department: string }

export interface BookingRequest {
  office_id: number; start_at: string; end_at: string; vehicle_id?: number | null; slot_id?: number | null;
  visitor?: { name: string; plate_number: string; vehicle_type: VehicleType; phone: string } | null;
  prefer_ev?: boolean; prefer_accessible?: boolean; notes?: string; user_id?: number | null;
}

const P = "/api";
export const parkingApi = {
  offices: (start: string, end: string, vehicle_type = "", include_inactive = false) =>
    get(`${P}/offices`, { start, end, vehicle_type, include_inactive: include_inactive || undefined }) as Promise<OfficeSummary[]>,
  availability: (id: number, start: string, end: string) =>
    get(`${P}/offices/${id}/availability`, { start, end }) as Promise<Availability>,
  myVehicles: () => get(`${P}/me/vehicles`) as Promise<MyVehicle[]>,
  addVehicle: (b: { plate_number: string; vehicle_type: VehicleType; notes?: string }) => post(`${P}/me/vehicles`, b) as Promise<MyVehicle>,
  updateVehicle: (id: number, b: { plate_number: string; vehicle_type: VehicleType; notes?: string }) =>
    put(`${P}/me/vehicles/${id}`, b) as Promise<MyVehicle>,
  removeVehicle: (id: number) => del(`${P}/me/vehicles/${id}`) as Promise<null>,
  book: (b: BookingRequest) => post(`${P}/bookings`, b) as Promise<Booking>,
  myBookings: (scope: "upcoming" | "past" | "all", page = 1) =>
    get(`${P}/me/bookings`, { scope, page }) as Promise<Page<Booking>>,
  booking: (id: number) => get(`${P}/bookings/${id}`) as Promise<Booking>,
  cancel: (id: number, reason = "") => post(`${P}/bookings/${id}/cancel`, { reason }) as Promise<Booking>,
  change: (id: number, start_at: string, end_at: string) => put(`${P}/bookings/${id}`, { start_at, end_at }) as Promise<Booking>,
  updateProfile: (b: { full_name?: string; phone?: string; department?: string }) => put(`${P}/me/profile`, b),
  // security
  scan: (text: string) => post(`${P}/bookings/scan`, { text }) as Promise<Booking>,
  checkIn: (id: number) => post(`${P}/bookings/${id}/check-in`) as Promise<Booking>,
  checkOut: (id: number) => post(`${P}/bookings/${id}/check-out`) as Promise<Booking>,
  allBookings: (params: { office_id?: number | ""; day?: string; status?: string; q?: string; page?: number; page_size?: number }) =>
    get(`${P}/bookings`, params) as Promise<Page<Booking> & { counts: Record<string, number> }>,
  // administration
  createOffice: (b: Partial<Office>) => post(`${P}/offices`, b) as Promise<Office>,
  updateOffice: (id: number, b: Partial<Office>) => put(`${P}/offices/${id}`, b) as Promise<Office>,
  deleteOffice: (id: number) => del(`${P}/offices/${id}`),
  addFloor: (officeId: number, name: string, level: number) => post(`${P}/offices/${officeId}/floors`, { name, level }) as Promise<Office>,
  updateFloor: (id: number, name: string, level: number) => put(`${P}/floors/${id}`, { name, level }) as Promise<Office>,
  deleteFloor: (id: number) => del(`${P}/floors/${id}`),
  addZone: (floorId: number, name: string) => post(`${P}/floors/${floorId}/zones`, { name }) as Promise<Office>,
  renameZone: (id: number, name: string) => put(`${P}/zones/${id}`, { name }) as Promise<Office>,
  deleteZone: (id: number) => del(`${P}/zones/${id}`),
  slots: (officeId: number) => get(`${P}/offices/${officeId}/slots`) as Promise<Slot[]>,
  addSlots: (zoneId: number, b: { prefix: string; start: number; count: number; digits: number; vehicle_type: VehicleType;
    is_ev: boolean; is_accessible: boolean; is_visitor: boolean }) =>
    post(`${P}/zones/${zoneId}/slots`, b) as Promise<{ created: number; codes: string[] }>,
  updateSlot: (id: number, b: Partial<Slot>) => put(`${P}/slots/${id}`, b) as Promise<Slot>,
  deleteSlot: (id: number) => del(`${P}/slots/${id}`),
  people: (q: string) => get(`${P}/people`, { q }) as Promise<Person[]>,
};

// ---------------------------------------------------------------- time helpers
const pad = (n: number) => String(n).padStart(2, "0");
/** "YYYY-MM-DD" of a local date. */
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
/** Local date + "HH:MM" -> ISO string (UTC). */
export const atLocal = (day: string, hhmm: string) => new Date(`${day}T${hhmm}`).toISOString();
export const hhmm = (iso: string) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const fmtDay = (iso: string) => new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
export const fmtRange = (s: string, e: string) => {
  const sameDay = ymd(new Date(s)) === ymd(new Date(e));
  return sameDay ? `${fmtDay(s)}, ${hhmm(s)}–${hhmm(e)}` : `${fmtDay(s)} ${hhmm(s)} – ${fmtDay(e)} ${hhmm(e)}`;
};
/** Next quarter hour from now, as "HH:MM". */
export function nextQuarter(): string {
  const d = new Date(Date.now() + 5 * 60000);
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const VEHICLE_LABEL: Record<VehicleType, string> = { CAR: "Car", TWO_WHEELER: "Two-wheeler", COMMERCIAL: "Commercial" };

export const STATE_STYLE: Record<SlotState, { label: string; cls: string }> = {
  AVAILABLE: { label: "Free", cls: "bg-emerald-500 text-white ring-emerald-600 hover:bg-emerald-600" },
  BOOKED: { label: "Reserved", cls: "bg-amber-400 text-amber-950 ring-amber-500" },
  OCCUPIED: { label: "Occupied", cls: "bg-red-500 text-white ring-red-600" },
  MINE: { label: "Your booking", cls: "bg-navy-700 text-white ring-navy-900" },
  ASSIGNED: { label: "Assigned", cls: "bg-slate-300 text-slate-700 ring-slate-400" },
  OUT_OF_SERVICE: { label: "Out of service", cls: "bg-slate-200 text-slate-400 ring-slate-300 line-through" },
};

export const STATUS_STYLE: Record<BookingStatus, { label: string; color: string }> = {
  CONFIRMED: { label: "Confirmed", color: "blue" },
  CHECKED_IN: { label: "Parked", color: "green" },
  COMPLETED: { label: "Completed", color: "slate" },
  CANCELLED: { label: "Cancelled", color: "red" },
  NO_SHOW: { label: "No-show", color: "amber" },
};
