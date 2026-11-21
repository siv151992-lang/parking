import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import { RealtimeProvider } from "./lib/realtime";
import Login from "./pages/Login";

// Pages load on first visit, so the first screen downloads less.
const Alerts = lazy(() => import("./pages/Alerts"));
const CameraManagement = lazy(() => import("./pages/CameraManagement"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const LiveMonitoring = lazy(() => import("./pages/LiveMonitoring"));
const Occupancy = lazy(() => import("./pages/Occupancy"));
const Reports = lazy(() => import("./pages/Reports"));
const Settings = lazy(() => import("./pages/Settings"));
const Users = lazy(() => import("./pages/Users"));
const InOut = lazy(() => import("./pages/InOut"));
const VehicleHistory = lazy(() => import("./pages/VehicleHistory"));

function Guard({ perm, children }) {
  const { can } = useAuth();
  if (!can(perm))
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-500">
        You don&apos;t have permission to view this page.
      </div>
    );
  return children;
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user)
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  return (
    <RealtimeProvider enabled={!!user}>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route element={<Layout />}>
          <Route index element={<Guard perm="dashboard.view"><Dashboard /></Guard>} />
          <Route path="live" element={<Guard perm="cameras.view"><LiveMonitoring /></Guard>} />
          <Route path="cameras" element={<Guard perm="cameras.view"><CameraManagement /></Guard>} />
          <Route path="entries" element={<Guard perm="vehicles.view"><InOut /></Guard>} />
          <Route path="exits" element={<Navigate to="/entries?tab=exit" replace />} />
          <Route path="history" element={<Guard perm="vehicles.view"><VehicleHistory /></Guard>} />
          <Route path="occupancy" element={<Guard perm="occupancy.view"><Occupancy /></Guard>} />
          <Route path="reports" element={<Guard perm="reports.view"><Reports /></Guard>} />
          <Route path="alerts" element={<Guard perm="alerts.view"><Alerts /></Guard>} />
          <Route path="users" element={<Guard perm="users.manage"><Users /></Guard>} />
          <Route path="settings" element={<Guard perm="settings.view"><Settings /></Guard>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </RealtimeProvider>
  );
}
