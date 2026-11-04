import { useRef, useState } from "react";
import { CheckCircle2, Download, FileUp } from "lucide-react";
import { post, upload } from "../lib/api";
import { Badge, Button, Field, Input, Modal, Table, useToast } from "../components/ui";

// Column names accepted in a header row (any case); without a header the order is fixed.
const FIELDS = [
  ["name", ["name", "camera", "camera name"]],
  ["position", ["position", "camera position", "where", "type"]],
  ["ip_address", ["ip", "ip address", "address", "host"]],
  ["username", ["username", "user", "login", "user name"]],
  ["password", ["password", "pass", "pwd"]],
  ["rtsp_url", ["rtsp", "rtsp url", "url", "stream", "video address"]],
  ["location", ["location", "place", "area"]],
];
const ORDER = FIELDS.map(([k]) => k);

const TEMPLATE = [
  ["Name", "Position", "IP address", "Username", "Password", "RTSP URL (optional)", "Location (optional)"],
  ["Main gate in", "Gate in", "192.168.1.64", "admin", "", "", "Gate 1"],
  ["Main gate out", "Gate out", "192.168.1.65", "admin", "", "", "Gate 1"],
  ["Row A in", "Row A in", "192.168.1.71", "admin", "", "", ""],
  ["Row A out", "Row A out", "192.168.1.72", "admin", "", "", ""],
];

function splitLine(line, delim) {
  const out = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"' && cur === "") quoted = true;
    else if (ch === delim) { out.push(cur.trim()); cur = ""; }
    else cur += ch;
  }
  out.push(cur.trim());
  return out;
}

export function textToRows(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  const first = lines[0];
  const delim = text.includes("\t") ? "\t" : (first.split(";").length > first.split(",").length ? ";" : ",");
  return lines.map((l) => splitLine(l, delim));
}

/** Rows of cells -> camera objects. A first row of column names is used to map columns. */
export function rowsToCameras(rows) {
  if (!rows.length) return [];
  const norm = (s) => String(s || "").toLowerCase().replace(/\(.*?\)/g, "").replace(/\s+/g, " ").trim();
  const header = rows[0].map(norm);
  const map = header.map((h) => FIELDS.find(([, names]) => names.includes(h))?.[0] || null);
  const hasHeader = map.filter(Boolean).length >= 2;
  const cols = hasHeader ? map : ORDER;
  return (hasHeader ? rows.slice(1) : rows).map((r) => {
    const cam = {};
    cols.forEach((k, i) => { if (k) cam[k] = String(r[i] ?? "").trim(); });
    return cam;
  });
}

function downloadTemplate() {
  const csv = TEMPLATE.map((r) => r.map((v) => (/[",;]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "cameras-template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

const CONN = {
  ok: ["green", "Answers"],
  auth: ["red", "Login wrong"],
  unreachable: ["red", "No answer"],
  path: ["amber", "Video address not found"],
  other: ["amber", "Problem"],
};

export default function BulkCameras({ open, onClose, onDone, rows }) {
  const toast = useToast();
  const fileRef = useRef(null);
  const [text, setText] = useState("");
  const [defaults, setDefaults] = useState({ username: "admin", password: "" });
  const [checkConn, setCheckConn] = useState(true);
  const [review, setReview] = useState(null); // { cameras, result }
  const [busy, setBusy] = useState(false);

  const reset = () => { setReview(null); setText(""); };
  const close = () => { reset(); onClose(); };
  const cameras = rowsToCameras(textToRows(text));

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    try {
      const { rows: cells } = await upload("/api/cameras/bulk/parse-file", f);
      setText(cells.map((r) => r.join("\t")).join("\n"));
      toast(`Read ${Math.max(0, cells.length - 1)} lines from ${f.name}`, "success");
    } catch (err) {
      toast(err.message, "error");
    }
  };

  const check = async () => {
    if (!cameras.length) return toast("Paste or upload the list of cameras first", "error");
    setBusy(true);
    try {
      const result = await post("/api/cameras/bulk", {
        cameras, default_username: defaults.username, default_password: defaults.password, dry_run: true, check_connection: checkConn,
      });
      setReview({ cameras, result });
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    setBusy(true);
    try {
      // keep the video addresses the check found
      const list = review.cameras.map((c, i) => ({ ...c, rtsp_url: review.result.lines[i]?.rtsp_url || c.rtsp_url || "" }));
      const r = await post("/api/cameras/bulk", {
        cameras: list, default_username: defaults.username, default_password: defaults.password, dry_run: false, check_connection: false,
      });
      toast(`Added ${r.created} camera${r.created === 1 ? "" : "s"}${r.skipped ? ` · ${r.skipped} skipped` : ""}`, "success");
      reset();
      onDone();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const valid = review?.result.valid || 0;
  const footer = review ? (
    <>
      <Button variant="secondary" onClick={() => setReview(null)}>Back to the list</Button>
      <Button onClick={add} loading={busy} disabled={!valid}>Add {valid} camera{valid === 1 ? "" : "s"}</Button>
    </>
  ) : (
    <>
      <Button variant="secondary" onClick={close}>Cancel</Button>
      <Button onClick={check} loading={busy} disabled={!cameras.length}>
        {busy && checkConn ? "Checking cameras…" : `Check ${cameras.length || ""} camera${cameras.length === 1 ? "" : "s"}`}
      </Button>
    </>
  );

  return (
    <Modal open={open} onClose={close} title={review ? "Check the cameras" : "Add many cameras"} wide footer={footer}>
      {!review ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            One camera per line: <b>Name, Position, IP address, Username, Password</b>. Copy the rows from Excel and paste them here, or upload the Excel / CSV file.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" icon={FileUp} onClick={() => fileRef.current?.click()}>Upload Excel / CSV</Button>
            <Button variant="ghost" icon={Download} onClick={downloadTemplate}>Download template</Button>
            <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv,.txt" className="hidden" onChange={onFile} />
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={9} spellCheck={false}
            aria-label="Camera list"
            placeholder={"Main gate in\tGate in\t192.168.1.64\nMain gate out\tGate out\t192.168.1.65\nRow A in\tRow A in\t192.168.1.71\nRow A out\tRow A out\t192.168.1.72"}
            className="w-full rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-navy-600 outline-none p-3 font-mono text-xs" />
          <div className="text-xs text-slate-500 space-y-1">
            <p><b>Position</b>: <code>Gate in</code>, <code>Gate out</code>, or a row and in/out, for example <code>Row A in</code>, <code>Row A out</code>.
              {rows.length ? ` Your rows: ${rows.map((r) => r.name).join(", ")}.` : " Add rows under Parking Spaces first to use row positions."}</p>
            <p>Leave username / password empty on a line to use the ones below. The video address is found automatically.</p>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 items-end">
            <Field label="Username for all cameras"><Input value={defaults.username} onChange={(e) => setDefaults({ ...defaults, username: e.target.value })} autoComplete="off" /></Field>
            <Field label="Password for all cameras"><Input type="password" value={defaults.password} onChange={(e) => setDefaults({ ...defaults, password: e.target.value })} autoComplete="new-password" /></Field>
            <label className="flex items-center gap-2 text-sm pb-2"><input type="checkbox" checked={checkConn} onChange={(e) => setCheckConn(e.target.checked)} /> Check each camera answers</label>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600 flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-600" />
            {valid} ready to add{review.result.invalid ? `, ${review.result.invalid} with errors (they will be skipped)` : ""}. Nothing is saved until you click Add.
          </p>
          <div className="max-h-[55vh] overflow-y-auto -mx-4">
            <Table
              rowKey="line"
              rows={review.result.lines}
              columns={[
                { key: "line", label: "#", render: (l) => <span className="text-xs text-slate-400 tabular-nums">{l.line}</span> },
                { key: "name", label: "Camera", render: (l) => <div><p className="font-medium text-slate-900">{l.name || "—"}</p><p className="text-[11px] text-slate-500">{l.camera_code || ""}</p></div> },
                { key: "position", label: "Position", render: (l) => <span className="text-sm whitespace-nowrap">{l.position || "—"}</span> },
                { key: "ip_address", label: "IP", render: (l) => <span className="font-mono text-xs">{l.ip_address || "—"}</span> },
                { key: "connection", label: "Camera check", render: (l) => {
                  if (!l.connection) return <span className="text-xs text-slate-400">{l.errors.length ? "" : "not checked"}</span>;
                  const [color, label] = CONN[l.connection] || CONN.other;
                  return <Badge color={color} title={l.message}>{label}</Badge>;
                } },
                { key: "result", label: "Result", render: (l) => l.errors.length ? (
                  <p className="text-xs text-red-700 w-72 whitespace-normal">{l.errors.join(". ")}</p>
                ) : (
                  <div className="w-72 whitespace-normal">
                    <p className="text-xs font-medium text-emerald-700">Ready</p>
                    {l.warnings.map((w) => <p key={w} className="text-[11px] text-amber-700">{w}</p>)}
                  </div>
                ) },
              ]}
            />
          </div>
          {review.result.lines.some((l) => !l.errors.length && l.connection && l.connection !== "ok") && (
            <p className="text-xs text-amber-700">Cameras that did not answer can still be added: they keep trying to connect, and you can fix them later under Cameras.</p>
          )}
        </div>
      )}
    </Modal>
  );
}
