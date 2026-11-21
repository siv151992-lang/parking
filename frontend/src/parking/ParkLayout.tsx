// Layout for booking office parking: used by employees, and by staff via "Book parking".
import { Suspense } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { CalendarCheck, Car, LayoutDashboard, LogOut, MapPin, UserRound } from "lucide-react";
import { Spinner } from "./ui";
import { isStaff, useAuthT } from "./auth";

const NAV = [
  { to: "/park", label: "Book", icon: MapPin, end: true },
  { to: "/park/bookings", label: "My bookings", icon: CalendarCheck },
  { to: "/park/vehicles", label: "Vehicles", icon: Car },
  { to: "/park/profile", label: "Profile", icon: UserRound },
];

export default function ParkLayout() {
  const { user, logout } = useAuthT();
  const nav = useNavigate();
  return (
    <div className="min-h-screen bg-slate-50 pb-16 sm:pb-0">
      <header className="sticky top-0 z-20 bg-white/95 backdrop-blur border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
          <Link to="/park" className="flex items-center gap-2 font-bold text-navy-900 shrink-0">
            <span className="w-8 h-8 rounded-lg bg-navy-900 text-white flex items-center justify-center font-black">P</span>
            <span className="hidden lg:inline">Office Parking</span>
          </Link>
          <nav className="hidden sm:flex items-center gap-1" aria-label="Parking">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}
                title={label} aria-label={label}
                className={({ isActive }) => `flex items-center gap-1.5 px-2.5 lg:px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap ${isActive ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                <Icon size={16} /> <span className="hidden lg:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {isStaff(user) && (
              <Link to="/" className="flex items-center gap-1.5 text-sm font-medium text-navy-700 hover:underline">
                <LayoutDashboard size={16} /> <span className="hidden lg:inline">Console</span>
              </Link>
            )}
            <span className="hidden xl:block text-sm text-slate-600 max-w-[12rem] truncate" title={user.full_name || user.username}>{user.full_name || user.username}</span>
            <button type="button" onClick={() => logout().then(() => nav("/login"))} className="p-2 rounded-lg text-slate-500 hover:bg-slate-100" aria-label="Sign out" title="Sign out">
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-5">
        <Suspense fallback={<Spinner />}>
          <Outlet />
        </Suspense>
      </main>
      {/* bottom tab bar on phones */}
      <nav className="sm:hidden fixed bottom-0 inset-x-0 z-20 bg-white border-t border-slate-200 grid grid-cols-4" aria-label="Parking">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${isActive ? "text-navy-900" : "text-slate-500"}`}>
            <Icon size={20} /> {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
