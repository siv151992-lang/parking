export const fmtNum = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString());

export const fmtDateTime = (iso) => {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–");

export const fmtDuration = (sec) => {
  if (sec === null || sec === undefined) return "–";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
};

export const sinceNow = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

export const pct = (v) => `${Math.round((v || 0) * 100)}%`;

export const VEHICLE_TYPES = { CAR: "Car", TWO_WHEELER: "Two-Wheeler", COMMERCIAL: "Commercial" };
export const CATEGORIES = { CAR: "Car", TWO_WHEELER: "Two-Wheeler", HEAVY: "Heavy Vehicle", RESERVED: "Reserved" };
export const ROLES = {
  SUPER_ADMIN: "Super Admin",
  PARKING_MANAGER: "Parking Manager",
  SECURITY_OPERATOR: "Security Operator",
  REPORT_VIEWER: "Report Viewer",
};

export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const daysAgoISO = (n) => {
  const d = new Date(Date.now() - n * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
