import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FileSpreadsheet, FileText, FileType2 } from "lucide-react";
import { download, get } from "../lib/api";
import { daysAgoISO, todayISO } from "../lib/format";
import { Button, Card, Field, Input, PageHeader, Select, SERIES, Spinner, Table, useFetch, useToast } from "../components/ui";
import { ChartTooltip } from "./Dashboard";

const COLORS = [SERIES.entries, SERIES.exits, SERIES.third];
const SINGLE_DAY = ["daily_entry", "daily_exit", "hourly"];
const RANGE = ["weekly", "category", "camera", "peak_hours", "accuracy"];
const label = (k) => k.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());

function ReportChart({ rep }) {
  const c = rep.chart;
  if (!c) return null;
  // Pie-type data (shares of a whole) is shown as a single-series bar: easier to compare than a pie.
  if (c.kind === "pie") {
    const data = c.data || [];
    if (!data.length) return null;
    return (
      <div className="h-56">
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 24, right: 24 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} width={120} tickFormatter={label} />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
            <Bar dataKey="value" name="Count" fill={SERIES.entries} radius={[0, 4, 4, 0]} maxBarSize={22} label={{ position: "right", fontSize: 11, fill: "#334155" }} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  const rows = c.rows || rep.rows;
  if (!rows?.length) return null;
  const Chart = c.kind === "line" ? LineChart : BarChart;
  return (
    <div className="h-72">
      <ResponsiveContainer>
        <Chart data={rows} barGap={2} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey={c.x} tickLine={false} axisLine={false} minTickGap={12} />
          <YAxis allowDecimals tickLine={false} axisLine={false} />
          <Tooltip content={<ChartTooltip />} cursor={c.kind === "line" ? { stroke: "#94a3b8" } : { fill: "#f1f5f9" }} />
          {c.series.length > 1 && <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} formatter={label} />}
          {c.series.map((s, i) =>
            c.kind === "line" ? (
              <Line key={s} dataKey={s} name={label(s)} stroke={COLORS[i]} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }} />
            ) : (
              <Bar key={s} dataKey={s} name={label(s)} fill={COLORS[i]} radius={[4, 4, 0, 0]} maxBarSize={18} />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Reports() {
  const toast = useToast();
  const types = useFetch(() => get("/api/reports/types"), []);
  const [q, setQ] = useState({ type: "hourly", start: todayISO(), end: todayISO(), include_simulated: "true" });
  const rep = useFetch(() => get(`/api/reports/${q.type}`, { start: q.start, end: SINGLE_DAY.includes(q.type) || q.type === "monthly" || q.type === "occupancy" ? undefined : q.end, include_simulated: q.include_simulated }), [JSON.stringify(q)]);
  const [busy, setBusy] = useState("");

  const setType = (type) => {
    if (RANGE.includes(type)) setQ({ ...q, type, start: daysAgoISO(6), end: todayISO() });
    else if (type === "monthly") setQ({ ...q, type, start: todayISO().slice(0, 8) + "01" });
    else setQ({ ...q, type, start: todayISO(), end: todayISO() });
  };

  const exp = async (format) => {
    setBusy(format);
    try {
      await download(`/api/reports/${q.type}/export`, { format, start: q.start, end: RANGE.includes(q.type) ? q.end : undefined, include_simulated: q.include_simulated }, `${q.type}.${format}`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy("");
    }
  };

  const r = rep.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Reports & Analytics" subtitle="Generated from transactions and detections in the database">
        <Button variant="secondary" icon={FileText} loading={busy === "csv"} onClick={() => exp("csv")}>CSV</Button>
        <Button variant="secondary" icon={FileSpreadsheet} loading={busy === "xlsx"} onClick={() => exp("xlsx")}>Excel</Button>
        <Button variant="secondary" icon={FileType2} loading={busy === "pdf"} onClick={() => exp("pdf")}>PDF</Button>
      </PageHeader>

      <Card>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Report">
            <Select value={q.type} onChange={(e) => setType(e.target.value)} options={(types.data || []).map((t) => ({ value: t.key, label: t.title }))} />
          </Field>
          {q.type !== "occupancy" && (
            <Field label={q.type === "monthly" ? "Month" : RANGE.includes(q.type) ? "From" : "Date"}>
              {q.type === "monthly" ? (
                <Input type="month" value={q.start.slice(0, 7)} onChange={(e) => setQ({ ...q, start: `${e.target.value}-01` })} />
              ) : (
                <Input type="date" value={q.start} max={todayISO()} onChange={(e) => setQ({ ...q, start: e.target.value })} />
              )}
            </Field>
          )}
          {RANGE.includes(q.type) && (
            <Field label="To"><Input type="date" value={q.end} max={todayISO()} onChange={(e) => setQ({ ...q, end: e.target.value })} /></Field>
          )}
          <Field label="Data source">
            <Select value={q.include_simulated} onChange={(e) => setQ({ ...q, include_simulated: e.target.value })} options={[{ value: "true", label: "Real + simulated" }, { value: "false", label: "Real cameras only" }]} />
          </Field>
        </div>
      </Card>

      {rep.loading && !r ? <Spinner /> : rep.error ? <p className="text-red-600">{rep.error.message}</p> : r && (
        <>
          <div>
            <h2 className="text-lg font-semibold text-navy-900">{r.title}</h2>
            <p className="text-sm text-slate-500">{r.facility} · {r.subtitle} · generated {r.generated_at}</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(r.summary).filter(([k]) => k !== "Note").map(([k, v]) => (
              <div key={k} className="bg-white rounded-xl border border-slate-200 p-3">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p>
                <p className="text-lg font-bold text-navy-900 tabular-nums truncate" title={String(v)}>{v}</p>
              </div>
            ))}
          </div>
          {r.summary.Note && <p className="text-xs text-slate-500">{r.summary.Note}</p>}
          <Card title="Chart"><ReportChart rep={r} /></Card>
          <Card title={`Data (${r.rows.length} rows)`} bodyClass="p-0">
            <Table rows={r.rows} rowKey="__none" columns={r.columns.map((c) => ({ key: c.key, label: c.label }))} />
          </Card>
        </>
      )}
    </div>
  );
}
