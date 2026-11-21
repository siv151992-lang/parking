// Administration of offices, floors, zones and slots.
import { useMemo, useState } from "react";
import { Accessibility, BatteryCharging, Building2, Pencil, Plus, Trash2, UserRound } from "lucide-react";
import type { Office, OfficeSummary, Person, Slot, VehicleType } from "./api";
import { VEHICLE_LABEL, parkingApi } from "./api";
import { LocationPicker } from "./components";
import { useFetchT, useToastT } from "./hooks";
import { Badge, Button, Card, Modal, PageHeader, Spinner } from "./ui";

const field = "block w-full rounded-lg border-0 py-2 px-3 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-navy-600 bg-white";
const Label = ({ text, children }: { text: string; children: React.ReactNode }) => (
  <label className="block"><span className="block text-xs font-medium text-slate-600 mb-1">{text}</span>{children}</label>
);

type OfficeForm = Partial<Office> & { name: string };
const EMPTY_OFFICE: OfficeForm = { name: "", city: "", address: "", latitude: null, longitude: null, is_24h: false, open_time: "07:00", close_time: "22:00", is_active: true, notes: "" };
type Confirm = { title: string; text: string; run: () => Promise<unknown>; done: string };

export default function OfficesAdmin() {
  const toast = useToastT();
  const offices = useFetchT<OfficeSummary[]>(() => {
    const now = new Date();
    return parkingApi.offices(now.toISOString(), new Date(now.getTime() + 60000).toISOString(), "", true);
  }, []);
  const [sel, setSel] = useState<number | null>(null);
  const current = offices.data?.find((o) => o.id === sel) || offices.data?.[0] || null;
  const slots = useFetchT<Slot[]>(() => (current ? parkingApi.slots(current.id) : Promise.resolve([])), [current?.id]);

  const [officeForm, setOfficeForm] = useState<OfficeForm | null>(null);
  const [nameForm, setNameForm] = useState<{ kind: "floor" | "zone"; id?: number; parent?: number; name: string; level: number } | null>(null);
  const [bulk, setBulk] = useState<{ zoneId: number; zone: string; prefix: string; start: number; count: number; digits: number; vehicle_type: VehicleType; is_ev: boolean; is_accessible: boolean; is_visitor: boolean } | null>(null);
  const [slotForm, setSlotForm] = useState<Slot | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast(msg, "success");
      setOfficeForm(null); setNameForm(null); setBulk(null); setSlotForm(null); setConfirm(null);
      await offices.reload();
      slots.reload();
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const byZone = useMemo(() => {
    const m = new Map<number, Slot[]>();
    for (const s of slots.data || []) m.set(s.zone_id, [...(m.get(s.zone_id) || []), s]);
    return m;
  }, [slots.data]);

  const saveOffice = () => {
    if (!officeForm) return;
    const { id, ...body } = officeForm;
    delete (body as Partial<OfficeSummary>).floors;
    for (const k of ["slots_total", "slots_free", "ev_free", "accessible_free", "visitor_free"]) delete (body as Record<string, unknown>)[k];
    run(async () => {
      const o = id ? await parkingApi.updateOffice(id, body) : await parkingApi.createOffice(body);
      setSel(o.id);
    }, id ? "Office saved" : "Office added");
  };
  const saveName = () => {
    if (!nameForm) return;
    const { kind, id, parent, name, level } = nameForm;
    const fn = kind === "floor"
      ? (id ? () => parkingApi.updateFloor(id, name, level) : () => parkingApi.addFloor(parent as number, name, level))
      : (id ? () => parkingApi.renameZone(id, name) : () => parkingApi.addZone(parent as number, name));
    run(fn, `${kind === "floor" ? "Floor" : "Zone"} saved`);
  };
  const findPeople = async (q: string) => {
    try {
      setPeople(await parkingApi.people(q));
    } catch {
      setPeople([]);
    }
  };

  if (offices.loading && !offices.data) return <Spinner />;
  return (
    <div className="space-y-5">
      <PageHeader title="Offices & Slots" subtitle="Offices, floors, zones and parking slots that employees can book">
        <Button icon={Plus} onClick={() => setOfficeForm({ ...EMPTY_OFFICE })}>Add office</Button>
      </PageHeader>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5 items-start [&>*]:min-w-0">
        <ul className="space-y-2" aria-label="Offices">
          {(offices.data || []).map((o) => (
            <li key={o.id}>
              <button type="button" onClick={() => setSel(o.id)} aria-pressed={current?.id === o.id}
                className={`w-full text-left rounded-xl p-3 ring-1 transition ${current?.id === o.id ? "bg-navy-900 text-white ring-navy-900" : "bg-white ring-slate-200 hover:ring-navy-300"}`}>
                <p className="font-semibold flex items-center gap-2"><Building2 size={16} /> {o.name}</p>
                <p className={`text-xs mt-0.5 ${current?.id === o.id ? "text-slate-300" : "text-slate-500"}`}>{o.city || "—"} · {o.slots_total} slots{o.is_active ? "" : " · inactive"}</p>
              </button>
            </li>
          ))}
          {offices.data?.length === 0 && <li className="text-sm text-slate-500 bg-white rounded-xl ring-1 ring-slate-200 p-4">No offices yet. Add the first one.</li>}
        </ul>

        {current && (
          <div className="lg:col-span-3 space-y-4">
            <Card title={<span className="flex items-center gap-2">{current.name} {!current.is_active && <Badge color="amber">Inactive</Badge>}</span>}
              action={<div className="flex gap-1">
                <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setOfficeForm({ ...current })}>Edit</Button>
                <Button size="sm" variant="ghost" icon={Trash2} aria-label="Delete office" title="Delete office"
                  onClick={() => setConfirm({ title: `Delete ${current.name}?`, text: "All its floors, zones and slots are deleted. Offices with upcoming bookings cannot be deleted: mark them inactive instead.", run: () => parkingApi.deleteOffice(current.id), done: "Office deleted" })} />
              </div>}>
              <p className="text-sm text-slate-600">{[current.address, current.city].filter(Boolean).join(", ") || "No address"} · {current.is_24h ? "Open 24 hours" : `Parking open ${current.open_time}–${current.close_time}`}</p>
              <p className="text-sm text-slate-600 mt-1">{current.slots_total} slots · {current.slots_free} free now</p>
            </Card>

            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-navy-900">Floors, zones and slots</h2>
              <Button size="sm" icon={Plus} onClick={() => setNameForm({ kind: "floor", parent: current.id, name: "", level: current.floors.length })}>Add floor</Button>
            </div>
            {current.floors.length === 0 && <p className="text-sm text-slate-500 bg-white rounded-xl ring-1 ring-slate-200 p-4">Add a floor (for example "Basement 1"), then zones and slots.</p>}
            {current.floors.map((fl) => (
              <Card key={fl.id} title={`${fl.name} (level ${fl.level})`} action={<div className="flex gap-1">
                <Button size="sm" variant="secondary" icon={Plus} onClick={() => setNameForm({ kind: "zone", parent: fl.id, name: "", level: 0 })}>Zone</Button>
                <Button size="sm" variant="ghost" icon={Pencil} aria-label={`Rename ${fl.name}`} title="Rename" onClick={() => setNameForm({ kind: "floor", id: fl.id, name: fl.name, level: fl.level })} />
                <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete ${fl.name}`} title="Delete"
                  onClick={() => setConfirm({ title: `Delete floor ${fl.name}?`, text: "Its zones and slots are deleted too.", run: () => parkingApi.deleteFloor(fl.id), done: "Floor deleted" })} />
              </div>}>
                <div className="space-y-4">
                  {fl.zones.length === 0 && <p className="text-sm text-slate-500">No zones yet.</p>}
                  {fl.zones.map((z) => {
                    const list = byZone.get(z.id) || [];
                    return (
                      <div key={z.id}>
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                          <p className="text-sm font-semibold text-slate-800">Zone {z.name} <span className="font-normal text-slate-500">· {list.length} slots</span></p>
                          <div className="ml-auto flex gap-1">
                            <Button size="sm" variant="secondary" icon={Plus}
                              onClick={() => setBulk({ zoneId: z.id, zone: z.name, prefix: `${z.name.slice(0, 3).toUpperCase()}-`, start: list.length + 1, count: 10, digits: 2, vehicle_type: "CAR", is_ev: false, is_accessible: false, is_visitor: false })}>Slots</Button>
                            <Button size="sm" variant="ghost" icon={Pencil} aria-label={`Rename zone ${z.name}`} title="Rename" onClick={() => setNameForm({ kind: "zone", id: z.id, name: z.name, level: 0 })} />
                            <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete zone ${z.name}`} title="Delete"
                              onClick={() => setConfirm({ title: `Delete zone ${z.name}?`, text: `Its ${list.length} slots are deleted too.`, run: () => parkingApi.deleteZone(z.id), done: "Zone deleted" })} />
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {list.map((s) => (
                            <button key={s.id} type="button" onClick={() => { setSlotForm({ ...s }); setPeople([]); }} title={`Edit ${s.code}`}
                              className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold ring-1 flex items-center gap-1 ${s.status === "OUT_OF_SERVICE" ? "bg-slate-100 text-slate-400 ring-slate-200 line-through" : "bg-white ring-slate-300 hover:ring-navy-400 text-slate-800"}`}>
                              {s.code}
                              {s.vehicle_type !== "CAR" && <span className="font-normal text-slate-500">{s.vehicle_type === "TWO_WHEELER" ? "2W" : "HV"}</span>}
                              {s.is_ev && <BatteryCharging size={12} className="text-sky-600" aria-label="EV" />}
                              {s.is_accessible && <Accessibility size={12} className="text-sky-600" aria-label="Accessible" />}
                              {s.is_visitor && <UserRound size={12} className="text-violet-600" aria-label="Visitors" />}
                              {s.assigned_to && <span className="font-normal text-amber-700">· {s.assigned_to}</span>}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* ---- office form */}
      <Modal open={!!officeForm} onClose={() => setOfficeForm(null)} title={officeForm?.id ? `Edit ${officeForm.name}` : "Add office"} wide
        footer={<><Button variant="secondary" onClick={() => setOfficeForm(null)}>Cancel</Button>
          <Button loading={busy} disabled={!officeForm || officeForm.name.trim().length < 2} onClick={saveOffice}>Save</Button></>}>
        {officeForm && (
          <div className="grid sm:grid-cols-2 gap-3">
            <Label text="Office name *"><input className={field} value={officeForm.name} onChange={(e) => setOfficeForm({ ...officeForm, name: e.target.value })} /></Label>
            <Label text="City"><input className={field} value={officeForm.city || ""} onChange={(e) => setOfficeForm({ ...officeForm, city: e.target.value })} /></Label>
            <div className="sm:col-span-2"><Label text="Address"><input className={field} value={officeForm.address || ""} onChange={(e) => setOfficeForm({ ...officeForm, address: e.target.value })} /></Label></div>
            <div className="sm:col-span-2 space-y-1">
              <span className="block text-xs font-medium text-slate-600">Location (click the map) {officeForm.latitude != null && <span className="font-normal text-slate-500">{officeForm.latitude}, {officeForm.longitude}</span>}</span>
              <LocationPicker lat={officeForm.latitude ?? null} lng={officeForm.longitude ?? null} onPick={(lat, lng) => setOfficeForm((f) => f && { ...f, latitude: lat, longitude: lng })} />
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!officeForm.is_24h} onChange={(e) => setOfficeForm({ ...officeForm, is_24h: e.target.checked })} /> Parking open 24 hours</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!officeForm.is_active} onChange={(e) => setOfficeForm({ ...officeForm, is_active: e.target.checked })} /> Taking bookings</label>
            {!officeForm.is_24h && <>
              <Label text="Opens"><input type="time" className={field} value={officeForm.open_time} onChange={(e) => setOfficeForm({ ...officeForm, open_time: e.target.value })} /></Label>
              <Label text="Closes"><input type="time" className={field} value={officeForm.close_time} onChange={(e) => setOfficeForm({ ...officeForm, close_time: e.target.value })} /></Label>
            </>}
            <div className="sm:col-span-2"><Label text="Notes for employees"><input className={field} value={officeForm.notes || ""} onChange={(e) => setOfficeForm({ ...officeForm, notes: e.target.value })} /></Label></div>
          </div>
        )}
      </Modal>

      {/* ---- floor / zone name */}
      <Modal open={!!nameForm} onClose={() => setNameForm(null)} title={nameForm ? `${nameForm.id ? "Edit" : "Add"} ${nameForm.kind}` : ""}
        footer={<><Button variant="secondary" onClick={() => setNameForm(null)}>Cancel</Button>
          <Button loading={busy} disabled={!nameForm?.name.trim()} onClick={saveName}>Save</Button></>}>
        {nameForm && (
          <div className="grid grid-cols-3 gap-3">
            <div className={nameForm.kind === "floor" ? "col-span-2" : "col-span-3"}>
              <Label text="Name"><input className={field} value={nameForm.name} autoFocus placeholder={nameForm.kind === "floor" ? "Basement 1" : "A"}
                onChange={(e) => setNameForm({ ...nameForm, name: e.target.value })} /></Label>
            </div>
            {nameForm.kind === "floor" && <Label text="Level (sort order)"><input type="number" className={field} value={nameForm.level}
              onChange={(e) => setNameForm({ ...nameForm, level: Number(e.target.value) })} /></Label>}
          </div>
        )}
      </Modal>

      {/* ---- bulk slots */}
      <Modal open={!!bulk} onClose={() => setBulk(null)} title={`Add slots to zone ${bulk?.zone ?? ""}`}
        footer={<><Button variant="secondary" onClick={() => setBulk(null)}>Cancel</Button>
          <Button loading={busy} disabled={!bulk || bulk.count < 1}
            onClick={() => bulk && run(() => parkingApi.addSlots(bulk.zoneId, bulk), `${bulk.count} slots added`)}>Add {bulk?.count} slots</Button></>}>
        {bulk && (
          <div className="grid grid-cols-3 gap-3">
            <Label text="Prefix"><input className={field} value={bulk.prefix} onChange={(e) => setBulk({ ...bulk, prefix: e.target.value })} /></Label>
            <Label text="First number"><input type="number" min={0} className={field} value={bulk.start} onChange={(e) => setBulk({ ...bulk, start: Number(e.target.value) })} /></Label>
            <Label text="How many"><input type="number" min={1} max={500} className={field} value={bulk.count} onChange={(e) => setBulk({ ...bulk, count: Number(e.target.value) })} /></Label>
            <p className="col-span-3 text-sm text-slate-600">Creates <b>{bulk.prefix}{String(bulk.start).padStart(bulk.digits, "0")}</b> to <b>{bulk.prefix}{String(bulk.start + Math.max(1, bulk.count) - 1).padStart(bulk.digits, "0")}</b></p>
            <Label text="Vehicle type"><select className={field} value={bulk.vehicle_type} onChange={(e) => setBulk({ ...bulk, vehicle_type: e.target.value as VehicleType })}>
              {(Object.keys(VEHICLE_LABEL) as VehicleType[]).map((t) => <option key={t} value={t}>{VEHICLE_LABEL[t]}</option>)}</select></Label>
            <div className="col-span-2 flex flex-wrap items-end gap-4 pb-2 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={bulk.is_ev} onChange={(e) => setBulk({ ...bulk, is_ev: e.target.checked })} /> EV charger</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={bulk.is_accessible} onChange={(e) => setBulk({ ...bulk, is_accessible: e.target.checked })} /> Accessible</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={bulk.is_visitor} onChange={(e) => setBulk({ ...bulk, is_visitor: e.target.checked })} /> Visitors only</label>
            </div>
          </div>
        )}
      </Modal>

      {/* ---- one slot */}
      <Modal open={!!slotForm} onClose={() => setSlotForm(null)} title={`Slot ${slotForm?.code ?? ""}`}
        footer={<>
          <Button variant="danger" icon={Trash2} className="mr-auto" onClick={() => slotForm && setConfirm({ title: `Delete slot ${slotForm.code}?`, text: "Slots with upcoming bookings cannot be deleted: mark them out of service instead.", run: () => parkingApi.deleteSlot(slotForm.id), done: "Slot deleted" })}>Delete</Button>
          <Button variant="secondary" onClick={() => setSlotForm(null)}>Cancel</Button>
          <Button loading={busy} disabled={!slotForm?.code.trim()} onClick={() => slotForm && run(() => parkingApi.updateSlot(slotForm.id, {
            code: slotForm.code.trim(), vehicle_type: slotForm.vehicle_type, is_ev: slotForm.is_ev, is_accessible: slotForm.is_accessible,
            is_visitor: slotForm.is_visitor, status: slotForm.status, assigned_user_id: slotForm.assigned_user_id, zone_id: slotForm.zone_id,
          }), "Slot saved")}>Save</Button></>}>
        {slotForm && current && (
          <div className="grid grid-cols-2 gap-3">
            <Label text="Slot number"><input className={field} value={slotForm.code} onChange={(e) => setSlotForm({ ...slotForm, code: e.target.value })} /></Label>
            <Label text="Zone"><select className={field} value={slotForm.zone_id} onChange={(e) => setSlotForm({ ...slotForm, zone_id: Number(e.target.value) })}>
              {current.floors.flatMap((fl) => fl.zones.map((z) => <option key={z.id} value={z.id}>{fl.name} · {z.name}</option>))}</select></Label>
            <Label text="Vehicle type"><select className={field} value={slotForm.vehicle_type} onChange={(e) => setSlotForm({ ...slotForm, vehicle_type: e.target.value as VehicleType })}>
              {(Object.keys(VEHICLE_LABEL) as VehicleType[]).map((t) => <option key={t} value={t}>{VEHICLE_LABEL[t]}</option>)}</select></Label>
            <Label text="Status"><select className={field} value={slotForm.status} onChange={(e) => setSlotForm({ ...slotForm, status: e.target.value as Slot["status"] })}>
              <option value="ACTIVE">In service</option><option value="OUT_OF_SERVICE">Out of service</option></select></Label>
            <div className="col-span-2 flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={slotForm.is_ev} onChange={(e) => setSlotForm({ ...slotForm, is_ev: e.target.checked })} /> EV charger</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={slotForm.is_accessible} onChange={(e) => setSlotForm({ ...slotForm, is_accessible: e.target.checked })} /> Accessible</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={slotForm.is_visitor} onChange={(e) => setSlotForm({ ...slotForm, is_visitor: e.target.checked })} /> Visitors only</label>
            </div>
            <div className="col-span-2 space-y-1.5">
              <span className="block text-xs font-medium text-slate-600">Assigned permanently to</span>
              {slotForm.assigned_user_id ? (
                <p className="text-sm flex items-center gap-2">{slotForm.assigned_to || `user #${slotForm.assigned_user_id}`}
                  <button type="button" className="text-xs underline text-slate-500" onClick={() => setSlotForm({ ...slotForm, assigned_user_id: null, assigned_to: null })}>remove</button></p>
              ) : (
                <>
                  <input className={field} placeholder="Search a person by name…" onChange={(e) => findPeople(e.target.value)} />
                  {people.length > 0 && (
                    <ul className="max-h-36 overflow-y-auto rounded-lg ring-1 ring-slate-200 divide-y divide-slate-100">
                      {people.map((p) => (
                        <li key={p.id}><button type="button" className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50"
                          onClick={() => { setSlotForm({ ...slotForm, assigned_user_id: p.id, assigned_to: p.name }); setPeople([]); }}>
                          {p.name} <span className="text-xs text-slate-500">{p.department || p.username}</span></button></li>
                      ))}
                    </ul>
                  )}
                  <p className="text-[11px] text-slate-400">Nobody else can book an assigned slot.</p>
                </>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm?.title ?? ""}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Keep</Button>
          <Button variant="danger" loading={busy} onClick={() => confirm && run(confirm.run, confirm.done)}>Delete</Button></>}>
        <p className="text-sm">{confirm?.text}</p>
      </Modal>
    </div>
  );
}
