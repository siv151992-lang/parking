import { useSearchParams } from "react-router-dom";
import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { VehicleEntry, VehicleExit } from "./Transactions";

/** Vehicle entries and exits on one page, as two tabs. */
export default function InOut() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "exit" ? "exit" : "entry";
  const tabs = [["entry", "Vehicles in", ArrowDownToLine], ["exit", "Vehicles out", ArrowUpFromLine]];
  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-lg bg-slate-100 p-1" role="tablist">
        {tabs.map(([key, label, Icon]) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setParams(key === "exit" ? { tab: "exit" } : {})}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-sm font-medium ${tab === key ? "bg-white shadow-sm text-navy-900" : "text-slate-600 hover:text-slate-900"}`}>
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>
      {tab === "entry" ? <VehicleEntry /> : <VehicleExit />}
    </div>
  );
}
