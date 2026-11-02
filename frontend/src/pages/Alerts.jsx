import { useState } from "react";
import { AlertOctagon, AlertTriangle, CheckCheck, CheckCircle2, Info } from "lucide-react";
import { get, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveRefresh } from "../lib/realtime";
import { fmtDateTime, sinceNow } from "../lib/format";
import { Badge, Button, Card, PageHeader, Pagination, Plate, Select, SimBadge, Spinner, useFetch, useToast } from "../components/ui";

const TYPES = ["CAMERA_OFFLINE", "CAMERA_ONLINE", "CAPACITY_WARNING", "CAPACITY_FULL", "OCR_FAILED", "DUPLICATE_DETECTION", "UNMATCHED_EXIT", "SUSPICIOUS_VEHICLE", "COUNT_MISMATCH"];
const SEV = { CRITICAL: [AlertOctagon, "text-red-600 bg-red-50"], WARNING: [AlertTriangle, "text-amber-600 bg-amber-50"], INFO: [Info, "text-blue-600 bg-blue-50"] };

export default function Alerts() {
  const { can } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ alert_type: "", severity: "", resolved: "false", page: 1 });
  const data = useFetch(() => get("/api/alerts", { ...f, page_size: 25 }), [JSON.stringify(f)]);
  useLiveRefresh(["alert", "alert_updated"], data.reload, 500);

  const resolve = async (a) => {
    try {
      await post(`/api/alerts/${a.id}/resolve`);
      data.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const readAll = async () => {
    await post("/api/alerts/read-all");
    data.reload();
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Alerts" subtitle="Camera, capacity, recognition and security notifications — pushed live to every dashboard">
        <Button variant="secondary" icon={CheckCheck} onClick={readAll}>Mark all read</Button>
      </PageHeader>
      <Card bodyClass="p-0">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-3 border-b border-slate-100">
          <Select value={f.alert_type} onChange={(e) => setF({ ...f, alert_type: e.target.value, page: 1 })} options={[{ value: "", label: "All alert types" }, ...TYPES.map((t) => ({ value: t, label: t.replaceAll("_", " ") }))]} />
          <Select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value, page: 1 })} options={[{ value: "", label: "All severities" }, { value: "CRITICAL", label: "Critical" }, { value: "WARNING", label: "Warning" }, { value: "INFO", label: "Info" }]} />
          <Select value={f.resolved} onChange={(e) => setF({ ...f, resolved: e.target.value, page: 1 })} options={[{ value: "false", label: "Open" }, { value: "true", label: "Resolved" }, { value: "", label: "All" }]} />
        </div>
        {!data.data ? <Spinner /> : (
          <>
            <ul className="divide-y divide-slate-100">
              {data.data.items.map((a) => {
                const [Icon, cls] = SEV[a.severity] || SEV.INFO;
                return (
                  <li key={a.id} className={`px-4 py-3 flex gap-3 items-start ${a.is_read ? "" : "bg-blue-50/40"}`}>
                    <span className={`p-2 rounded-lg shrink-0 ${cls}`} title={a.severity}><Icon size={18} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-slate-900">{a.title}</p>
                        <Badge color={a.severity === "CRITICAL" ? "red" : a.severity === "WARNING" ? "amber" : "blue"}>{a.severity}</Badge>
                        <Badge>{a.alert_type.replaceAll("_", " ")}</Badge>
                        <SimBadge show={a.is_simulated} />
                        {a.plate_number && <Plate value={a.plate_number} />}
                      </div>
                      {a.message && <p className="text-sm text-slate-600 mt-0.5">{a.message}</p>}
                      <p className="text-xs text-slate-400 mt-1" title={fmtDateTime(a.created_at)}>{sinceNow(a.created_at)} · {fmtDateTime(a.created_at)}</p>
                    </div>
                    {a.is_resolved ? (
                      <span className="text-xs text-emerald-700 flex items-center gap-1 shrink-0"><CheckCircle2 size={14} /> Resolved</span>
                    ) : can("alerts.manage") && <Button size="sm" variant="secondary" onClick={() => resolve(a)}>Resolve</Button>}
                  </li>
                );
              })}
              {data.data.items.length === 0 && <li className="px-4 py-10 text-center text-slate-400">No alerts</li>}
            </ul>
            <Pagination page={f.page} pageSize={25} total={data.data.total} onChange={(page) => setF({ ...f, page })} />
          </>
        )}
      </Card>
    </div>
  );
}
