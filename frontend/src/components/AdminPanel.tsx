import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { CheckCircle2, ShieldCheck, UserPlus, UsersRound } from "lucide-react";

import { api, ApiError } from "../lib/api";
import type { AuthUser, UserCreate, UserRole } from "../types/api";

const roleLabels: Record<UserRole, string> = { investigator: "Investigator", analyst: "Analyst", administrator: "Administrator" };

export function AdminPanel({ currentUser }: { currentUser: AuthUser }) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [form, setForm] = useState<UserCreate>({ username: "", display_name: "", role: "analyst", password: "" });

  async function load() {
    setLoading(true); setError(null);
    try { setUsers(await api.listUsers()); }
    catch (caught) { setError(caught instanceof ApiError ? caught.message : "Unable to load users."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function create(event: FormEvent) {
    event.preventDefault(); setError(null); setSuccess(null);
    try {
      const created = await api.createUser(form);
      setUsers((previous) => [...previous, created]);
      setForm({ username: "", display_name: "", role: "analyst", password: "" });
      setSuccess(`${created.display_name} can now access SeaScan.`);
    } catch (caught) { setError(caught instanceof ApiError ? caught.message : "Unable to create user."); }
  }

  async function update(user: AuthUser, patch: { role?: UserRole; active?: boolean }) {
    setError(null); setSuccess(null);
    try {
      const updated = await api.updateUser(user.id, patch);
      setUsers((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setSuccess(`${updated.display_name}'s access was updated.`);
    } catch (caught) { setError(caught instanceof ApiError ? caught.message : "Unable to update user."); }
  }

  return <section className="admin-page" aria-labelledby="admin-title">
    <header className="admin-hero"><div><p className="eyebrow">Access governance</p><h2 id="admin-title">Users and operational roles</h2><p>Grant only the permissions each team member needs. Changes are enforced immediately by the API.</p></div><div className="admin-hero__badge"><ShieldCheck size={20} /><span><strong>Administrator</strong>Privileged session</span></div></header>
    {(error || success) && <p className={error ? "admin-message admin-message--error" : "admin-message"}>{error ?? success}</p>}
    <div className="admin-grid">
      <article className="admin-create"><div className="admin-section-title"><UserPlus size={19} /><div><h3>Add team member</h3><p>Create a named account with a defined role.</p></div></div>
        <form onSubmit={(event) => void create(event)}>
          <label><span>Full name</span><input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required minLength={2} /></label>
          <label><span>Username</span><input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required minLength={3} pattern="[a-zA-Z0-9._-]+" /></label>
          <label><span>Role</span><select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as UserRole })}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label><span>Temporary password</span><input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} minLength={12} required placeholder="12+ chars, upper/lowercase and number" /></label>
          <button type="submit"><UserPlus size={16} /> Create account</button>
        </form>
      </article>
      <article className="admin-directory"><div className="admin-section-title"><UsersRound size={19} /><div><h3>Team directory</h3><p>{loading ? "Loading accounts…" : `${users.filter((user) => user.active).length} active accounts`}</p></div></div>
        <div className="user-list">{users.map((user) => <div className={`user-row ${!user.active ? "user-row--disabled" : ""}`} key={user.id}>
          <div className="user-avatar">{user.display_name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase()}</div>
          <div className="user-identity"><strong>{user.display_name}{user.id === currentUser.id && <small> You</small>}</strong><span>@{user.username}</span></div>
          <select aria-label={`Role for ${user.display_name}`} value={user.role} disabled={user.id === currentUser.id} onChange={(event) => void update(user, { role: event.target.value as UserRole })}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <button type="button" disabled={user.id === currentUser.id} onClick={() => void update(user, { active: !user.active })}>{user.active ? "Disable" : "Enable"}</button>
          {user.active && <CheckCircle2 size={16} className="user-active" />}
        </div>)}</div>
      </article>
    </div>
  </section>;
}
