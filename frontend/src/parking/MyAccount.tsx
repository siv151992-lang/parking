// My vehicles and my profile.
import { useState } from "react";
import { Car, Pencil, Plus, Trash2 } from "lucide-react";
import type { MyVehicle, VehicleType } from "./api";
import { VEHICLE_LABEL, parkingApi } from "./api";
import { useAuthT } from "./auth";
import { useFetchT, useToastT } from "./hooks";
import { Button, Card, Modal, PasswordForm, Plate, Spinner } from "./ui";

const input = "block w-full rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600 disabled:bg-slate-50";

export function MyVehicles() {
  const data = useFetchT<MyVehicle[]>(() => parkingApi.myVehicles(), []);
  const toast = useToastT();
  const [form, setForm] = useState<{ id?: number; plate_number: string; vehicle_type: VehicleType; notes: string } | null>(null);
  const [remove, setRemove] = useState<MyVehicle | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast(msg, "success");
      setForm(null);
      setRemove(null);
      data.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const save = () => {
    if (!form) return;
    const body = { plate_number: form.plate_number.trim(), vehicle_type: form.vehicle_type, notes: form.notes };
    run(() => (form.id ? parkingApi.updateVehicle(form.id, body) : parkingApi.addVehicle(body)), form.id ? "Vehicle updated" : "Vehicle added");
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-navy-900">My vehicles</h1>
        <Button icon={Plus} onClick={() => setForm({ plate_number: "", vehicle_type: "CAR", notes: "" })}>Add vehicle</Button>
      </div>
      <p className="text-sm text-slate-500">Security and the number-plate cameras recognise your bookings by these vehicle numbers.</p>
      {data.loading && !data.data ? <Spinner /> : (
        <ul className="space-y-2.5">
          {(data.data || []).map((v) => (
            <li key={v.id} className="bg-white rounded-xl ring-1 ring-slate-200 p-4 flex items-center gap-3">
              <Car className="text-slate-400 shrink-0" size={22} />
              <div className="flex-1 min-w-0">
                <Plate value={v.plate_number} />
                <p className="text-xs text-slate-500 mt-1">{VEHICLE_LABEL[v.vehicle_type]}{v.notes ? ` · ${v.notes}` : ""}</p>
              </div>
              <Button size="sm" variant="ghost" icon={Pencil} aria-label={`Edit ${v.plate_number}`} title="Edit"
                onClick={() => setForm({ id: v.id, plate_number: v.plate_number, vehicle_type: v.vehicle_type, notes: v.notes })} />
              <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Remove ${v.plate_number}`} title="Remove" onClick={() => setRemove(v)} />
            </li>
          ))}
          {data.data?.length === 0 && <li className="bg-white rounded-xl ring-1 ring-slate-200 p-8 text-center text-sm text-slate-500">No vehicles yet. Add the vehicle you come to the office with.</li>}
        </ul>
      )}
      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Edit vehicle" : "Add vehicle"}
        footer={<><Button variant="secondary" onClick={() => setForm(null)}>Cancel</Button>
          <Button loading={busy} disabled={!form || form.plate_number.trim().length < 3} onClick={save}>Save</Button></>}>
        {form && (
          <div className="space-y-3">
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Vehicle number</span>
              <input className={`${input} uppercase`} value={form.plate_number} disabled={!!form.id} placeholder="KA01AB1234"
                onChange={(e) => setForm({ ...form, plate_number: e.target.value.toUpperCase() })} autoFocus /></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Type</span>
              <select className={input} value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value as VehicleType })}>
                {(Object.keys(VEHICLE_LABEL) as VehicleType[]).map((t) => <option key={t} value={t}>{VEHICLE_LABEL[t]}</option>)}
              </select></label>
            <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Note (optional, e.g. colour / model)</span>
              <input className={input} maxLength={200} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
          </div>
        )}
      </Modal>
      <Modal open={!!remove} onClose={() => setRemove(null)} title="Remove this vehicle?"
        footer={<><Button variant="secondary" onClick={() => setRemove(null)}>Keep</Button>
          <Button variant="danger" loading={busy} onClick={() => remove && run(() => parkingApi.removeVehicle(remove.id), "Vehicle removed")}>Remove</Button></>}>
        <p className="text-sm">{remove?.plate_number} can no longer be booked by you. Vehicles with upcoming bookings cannot be removed.</p>
      </Modal>
    </div>
  );
}

export function MyProfile() {
  const { user, setUser } = useAuthT();
  const toast = useToastT();
  const [form, setForm] = useState({ full_name: user.full_name, phone: user.phone || "", department: user.department || "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const u = await parkingApi.updateProfile(form);
      setUser({ ...user, ...(u as object) });
      toast("Profile saved", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4 max-w-3xl">
      <h1 className="text-2xl font-bold text-navy-900">Profile</h1>
      <Card title="My details">
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block sm:col-span-2"><span className="block text-xs font-medium text-slate-600 mb-1">Name</span>
            <input className={input} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
          <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Phone</span>
            <input className={input} type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">Department</span>
            <input className={input} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></label>
          <p className="sm:col-span-2 text-xs text-slate-500">Signed in as {user.username}</p>
        </div>
        <div className="mt-4"><Button loading={busy} disabled={form.full_name.trim().length < 2} onClick={save}>Save</Button></div>
      </Card>
      <Card title="Change password"><div className="max-w-sm"><PasswordForm /></div></Card>
    </div>
  );
}
