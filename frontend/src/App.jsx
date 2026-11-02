import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import { RealtimeProvider } from "./lib/realtime";
import Alerts from "./pages/Alerts";
import CameraManagement from "./pages/CameraManagement";
import Dashboard from "./pages/Dashboard";
import LiveMonitoring from "./pages/LiveMonitoring";
import Login from "./pages/Login";
import Occupancy from "./pages/Occupancy";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Users from "./pages/Users";
import { VehicleEntry, VehicleExit } from "./pages/Transactions";
import VehicleHistory from "./pages/VehicleHistory";

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
          <Route path="entries" element={<Guard perm="vehicles.view"><VehicleEntry /></Guard>} />
          <Route path="exits" element={<Guard perm="vehicles.view"><VehicleExit /></Guard>} />
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
