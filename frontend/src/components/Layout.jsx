import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Bell, BarChart3, Camera, Car, History, LayoutDashboard, LogIn, LogOut, Menu, MonitorPlay, ParkingSquare,
  Settings, ShieldCheck, Users, X,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useEvent, useRealtime } from "../lib/realtime";
import { get } from "../lib/api";
import { ROLES } from "../lib/format";
import { useToast } from "./ui";

export const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, perm: "dashboard.view" },
  { to: "/live", label: "Live Camera Monitoring", icon: MonitorPlay, perm: "cameras.view" },
  { to: "/cameras", label: "Camera Management", icon: Camera, perm: "cameras.view" },
  { to: "/entries", label: "Vehicle Entry", icon: LogIn, perm: "vehicles.view" },
  { to: "/exits", label: "Vehicle Exit", icon: LogOut, perm: "vehicles.view" },
  { to: "/history", label: "Vehicle History", icon: History, perm: "vehicles.view" },
  { to: "/occupancy", label: "Parking Occupancy", icon: ParkingSquare, perm: "occupancy.view" },
  { to: "/reports", label: "Reports & Analytics", icon: BarChart3, perm: "reports.view" },
  { to: "/alerts", label: "Alerts", icon: Bell, perm: "alerts.view" },
  { to: "/users", label: "User Management", icon: Users, perm: "users.manage" },
  { to: "/settings", label: "Settings", icon: Settings, perm: "settings.view" },
];

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { connected } = useRealtime();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const toast = useToast();
  const nav = useNavigate();
  const loc = useLocation();

  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (can("alerts.view")) get("/api/alerts", { page_size: 1 }).then((r) => setUnread(r.unread)).catch(() => {});
  }, [can]);

  useEvent("alert", (a) => {
    setUnread((n) => n + 1);
    if (a.severity === "CRITICAL" || a.alert_type === "UNMATCHED_EXIT" || a.alert_type === "CAPACITY_WARNING") {
      toast(`${a.is_simulated ? "[SIM] " : ""}${a.title}`, a.severity === "CRITICAL" ? "error" : "warning");
    }
  });
  useEvent("alerts_read", () => setUnread(0));

  const items = NAV.filter((n) => can(n.perm));
  const current = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));

  return (
    <div className="min-h-screen flex">
      {open && <div className="fixed inset-0 bg-navy-950/50 z-30 lg:hidden" onClick={() => setOpen(false)} />}
      <aside
        className={`fixed lg:sticky top-0 z-40 h-screen w-64 shrink-0 bg-navy-900 text-slate-300 flex flex-col transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-white/10">
          <div className="w-9 h-9 rounded-lg bg-white text-navy-900 flex items-center justify-center font-black text-lg">P</div>
          <div className="leading-tight">
            <p className="font-bold text-white">Smart Parking</p>
            <p className="text-[11px] text-slate-400">ANPR Management</p>
          </div>
          <button className="ml-auto lg:hidden p-1 text-slate-400" onClick={() => setOpen(false)} aria-label="Close menu">
            <X size={18} />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto py-3 px-3 space-y-0.5">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition ${isActive ? "bg-white text-navy-900" : "hover:bg-white/10 hover:text-white"}`
              }
            >
              <Icon size={18} />
              <span className="flex-1">{label}</span>
              {to === "/alerts" && unread > 0 && (
                <span className="text-[10px] font-bold bg-red-500 text-white rounded-full px-1.5 py-0.5">{unread > 99 ? "99+" : unread}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-white/10">
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="w-9 h-9 rounded-full bg-navy-700 text-white flex items-center justify-center font-semibold uppercase">{user.username[0]}</div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-white truncate">{user.full_name || user.username}</p>
              <p className="text-[11px] text-slate-400 flex items-center gap-1">
                <ShieldCheck size={11} />
                {ROLES[user.role]}
              </p>
            </div>
            <button onClick={() => logout().then(() => nav("/login"))} className="p-2 rounded-lg hover:bg-white/10" title="Sign out" aria-label="Sign out">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-20 h-16 bg-white/90 backdrop-blur border-b border-slate-200 flex items-center gap-3 px-4 sm:px-6">
          <button className="lg:hidden p-2 -ml-2 rounded-lg hover:bg-slate-100" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2 min-w-0">
            <Car size={18} className="text-navy-700 shrink-0 hidden sm:block" />
            <span className="font-semibold text-navy-900 truncate">{current?.label || "Smart Parking"}</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span
              className={`hidden sm:inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ${connected ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}
              title="Real-time WebSocket connection"
            >
              <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
              {connected ? "Live" : "Reconnecting…"}
            </span>
            {can("alerts.view") && (
              <button onClick={() => nav("/alerts")} className="relative p-2 rounded-lg hover:bg-slate-100 text-slate-600" aria-label="Alerts">
                <Bell size={20} />
                {unread > 0 && <span className="absolute top-1 right-1 w-4 h-4 text-[9px] font-bold bg-red-500 text-white rounded-full flex items-center justify-center">{unread > 9 ? "9+" : unread}</span>}
              </button>
            )}
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6 max-w-[1600px] w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
