import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, ROLES } from "../lib/format";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Spinner, Table, useFetch, useToast } from "../components/ui";

export default function Users() {
  const { user: me } = useAuth();
  const toast = useToast();
  const users = useFetch(() => get("/api/users"), []);
  const roles = useFetch(() => get("/api/users/roles"), []);
  const [form, setForm] = useState(null);

  const save = async () => {
    try {
      if (form.id) {
        const body = { email: form.email, full_name: form.full_name, role: form.role, is_active: form.is_active };
        if (form.password) body.password = form.password;
        await put(`/api/users/${form.id}`, body);
      } else await post("/api/users", form);
      toast("User saved", "success");
      setForm(null);
      users.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const remove = async (u) => {
    if (!window.confirm(`Delete user ${u.username}?`)) return;
    try {
      await del(`/api/users/${u.id}`);
      users.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  if (!users.data) return <Spinner />;
  const perms = roles.data?.permissions || {};
  return (
    <div className="space-y-5">
      <PageHeader title="User Management" subtitle="Role-based access control. Passwords are stored as bcrypt hashes.">
        <Button icon={Plus} onClick={() => setForm({ username: "", email: "", full_name: "", password: "", role: "SECURITY_OPERATOR", is_active: true })}>Add user</Button>
      </PageHeader>
      <Card bodyClass="p-0">
        <Table rows={users.data} columns={[
          { key: "username", label: "User", render: (u) => <div><p className="font-medium text-slate-900">{u.full_name || u.username}</p><p className="text-xs text-slate-500">@{u.username} · {u.email}</p></div> },
          { key: "role", label: "Role", render: (u) => <Badge color={u.role === "SUPER_ADMIN" ? "violet" : u.role === "PARKING_MANAGER" ? "blue" : u.role === "SECURITY_OPERATOR" ? "green" : "slate"}>{ROLES[u.role]}</Badge> },
          { key: "is_active", label: "Status", render: (u) => <Badge color={u.is_active ? "green" : "red"}>{u.is_active ? "Active" : "Disabled"}</Badge> },
          { key: "last_login_at", label: "Last login", render: (u) => fmtDateTime(u.last_login_at) },
          { key: "a", label: "", render: (u) => (
            <div className="flex gap-1 justify-end">
              <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setForm({ ...u, password: "" })} />
              {u.id !== me.id && <Button size="sm" variant="ghost" icon={Trash2} onClick={() => remove(u)} />}
            </div>
          ) },
        ]} />
      </Card>

      <Card title="Role permissions" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead><tr className="bg-slate-50 text-[11px] uppercase text-slate-500"><th className="text-left px-3 py-2">Permission</th>{Object.entries(ROLES).map(([k, v]) => <th key={k} className="px-3 py-2">{v}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">
              {Object.entries(perms).map(([p, rs]) => (
                <tr key={p}><td className="px-3 py-1.5 font-mono text-xs">{p}</td>{Object.keys(ROLES).map((r) => <td key={r} className="text-center">{rs.includes(r) ? <span className="text-emerald-600 font-bold" aria-label="allowed">✓</span> : <span className="text-slate-300" aria-label="denied">–</span>}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? `Edit ${form.username}` : "Add user"}
        footer={<><Button variant="secondary" onClick={() => setForm(null)}>Cancel</Button><Button onClick={save}>Save</Button></>}>
        {form && (
          <div className="space-y-3">
            {!form.id && <Field label="Username"><Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" /></Field>}
            <Field label="Full name"><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Role"><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} options={Object.entries(ROLES).map(([value, label]) => ({ value, label }))} /></Field>
            <Field label={form.id ? "New password (optional)" : "Password"} hint="Min. 8 characters with upper-case, lower-case and a digit">
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
            </Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active</label>
          </div>
        )}
      </Modal>
    </div>
  );
}
