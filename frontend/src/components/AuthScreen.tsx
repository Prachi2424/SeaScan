import { useState } from "react";
import type { FormEvent } from "react";
import { Anchor, ArrowRight, CheckCircle2, LockKeyhole, Radar, Satellite, ShieldCheck, Ship, UserRoundSearch, Waves } from "lucide-react";

import { api, ApiError, setAuthToken } from "../lib/api";
import type { AuthUser, UserRole } from "../types/api";

interface AuthScreenProps {
  onAuthenticated: (user: AuthUser) => void;
  developmentMode: boolean;
}

const accounts: { role: UserRole; username: string; label: string; icon: typeof Radar; description: string }[] = [
  { role: "investigator", username: "investigator", label: "Investigator", icon: Radar, description: "Create cases, ingest evidence, and run investigations." },
  { role: "analyst", username: "analyst", label: "Analyst", icon: UserRoundSearch, description: "Review cases, model drift, and assess vessel rankings." },
  { role: "administrator", username: "admin", label: "Administrator", icon: ShieldCheck, description: "Manage users, roles, and the complete platform." },
];

export function AuthScreen({ onAuthenticated, developmentMode }: AuthScreenProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.login(username, password);
      setAuthToken(response.access_token);
      onAuthenticated(response.user);
    } catch (caught) {
      setAuthToken(null);
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function chooseDemo(selected: typeof accounts[number]) {
    setUsername(selected.username);
    setPassword("SeaScan@2026");
    setError(null);
  }

  const selectedAccount = accounts.find((account) => account.username === username);

  return <main className="auth-shell">
    <header className="auth-header">
      <div className="auth-brand"><Anchor size={29} /><span>Sea<span>Scan</span></span></div>
      <nav aria-label="Welcome page">
        <a href="#capabilities">Capabilities</a>
        <a href="#role-access">Role access</a>
        <a href="#security">Security</a>
      </nav>
      <span className="auth-header__status"><i /> Operational</span>
    </header>

    <section className="auth-hero" aria-label="SeaScan secure access">
      <div className="auth-atmosphere" aria-hidden="true">
        <div className="auth-grid" />
        <div className="auth-coast auth-coast--one" />
        <div className="auth-coast auth-coast--two" />
        <div className="auth-radar"><span /><span /><span /><Radar size={42} /></div>
        <div className="auth-ocean-scene">
          <div className="ocean-wave ocean-wave--one" />
          <div className="ocean-wave ocean-wave--two" />
          <div className="oil-spill">
            <i /><i /><i /><i /><i />
            <span>Suspected discharge</span>
          </div>
          <div className="moving-vessel">
            <span className="moving-vessel__ping" />
            <div><Ship size={28} /></div>
            <small>SEA-047</small>
          </div>
          <div className="vessel-route" />
        </div>
      </div>

      <section className="auth-visual" id="capabilities">
        <div className="auth-visual__content">
          <p className="eyebrow"><Satellite size={13} /> AI-powered maritime intelligence</p>
          <h1>Trace pollution.<br /><span>Reveal its source.</span></h1>
          <p>Turn satellite detections, ocean drift, and AIS vessel history into one secure, evidence-led investigation.</p>
          <div className="auth-feature-strip">
            <span><Radar size={16} /> Spill detection</span>
            <span><Waves size={16} /> Drift reconstruction</span>
            <span><Ship size={16} /> Vessel attribution</span>
          </div>
        </div>

        {developmentMode && <div className="role-launcher" id="role-access">
          <div className="role-launcher__heading">
            <div><p className="eyebrow">Choose a workspace</p><h2>Continue with your operational role</h2></div>
            <span>Demo access</span>
          </div>
          <div className="role-launcher__grid">{accounts.map((account) => {
            const Icon = account.icon;
            const selected = username === account.username;
            return <button type="button" key={account.role} onClick={() => chooseDemo(account)} className={selected ? "selected" : ""} aria-pressed={selected}>
              <div className="role-launcher__icon"><Icon size={21} /></div>
              <span><strong>{account.label}</strong><small>{account.description}</small></span>
              <ArrowRight size={18} />
            </button>;
          })}</div>
        </div>}
      </section>

      <section className="auth-panel">
      <div className="auth-card">
        <div className="auth-card__top">
          <div className="auth-card__icon">{selectedAccount ? (() => { const Icon = selectedAccount.icon; return <Icon size={22} />; })() : <ShieldCheck size={22} />}</div>
          <span><LockKeyhole size={12} /> Secure access</span>
        </div>
        <p className="eyebrow">Identity verification</p>
        <h2>{selectedAccount ? `${selectedAccount.label} sign in` : "Sign in to SeaScan"}</h2>
        <p className="auth-card__intro">{selectedAccount?.description ?? "Use your assigned operational account."}</p>
        <form onSubmit={(event) => void submit(event)}>
          <label><span>Username</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Enter username" required /></label>
          <label><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter password" minLength={8} required /></label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? "Verifying identity…" : <>Enter secure workspace <ArrowRight size={16} /></>}</button>
        </form>
        {developmentMode && <p className="auth-demo-note"><CheckCircle2 size={14} /> Demo credentials filled automatically when you select a role.</p>}
      </div>
      <div className="auth-security" id="security"><ShieldCheck size={15} /><span><strong>Enterprise-ready access</strong> Password hashing · expiring sessions · server-enforced permissions</span></div>
      </section>
    </section>
  </main>;
}
