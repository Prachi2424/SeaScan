import { useState } from "react";
import type { FormEvent } from "react";
import { Anchor, ArrowRight, CheckCircle2, LockKeyhole, Radar, Satellite, ShieldCheck, Ship, UserRoundSearch, Waves, X } from "lucide-react";

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
  const [selectedRole, setSelectedRole] = useState<UserRole | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);

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

  function chooseRole(selected: typeof accounts[number]) {
    setSelectedRole(selected.role);
    setUsername(developmentMode ? selected.username : "");
    setPassword(developmentMode ? "SeaScan@2026" : "");
    setError(null);
    setLoginOpen(true);
  }

  const selectedAccount = accounts.find((account) => account.role === selectedRole);

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
          <svg className="oil-incident-illustration" viewBox="0 0 1200 620" role="presentation">
            <defs>
              <linearGradient id="seaGlow" x1="0" x2="1" y1="0" y2="1"><stop stopColor="#8be2ec" stopOpacity=".42" /><stop offset="1" stopColor="#08718c" stopOpacity=".08" /></linearGradient>
              <linearGradient id="tankerDeck" x1="0" x2="1"><stop stopColor="#f6b85b" /><stop offset="1" stopColor="#ef7e48" /></linearGradient>
              <filter id="sceneShadow"><feDropShadow dx="0" dy="12" stdDeviation="9" floodColor="#00394c" floodOpacity=".42" /></filter>
            </defs>
            <path className="illustration-current illustration-current--one" d="M-30 130 C220 70 350 190 590 125 S960 55 1240 145" />
            <path className="illustration-current illustration-current--two" d="M-50 505 C240 420 390 560 650 475 S990 400 1270 500" />
            <path className="illustration-slick" d="M245 340 C300 292 363 311 407 281 C462 244 520 293 571 267 C628 238 694 242 730 285 C764 326 738 349 790 374 C823 390 797 435 746 428 C694 421 674 467 620 455 C567 444 545 486 488 465 C439 447 416 476 364 446 C317 419 250 424 226 388 C211 366 220 352 245 340Z" />
            <path className="illustration-slick illustration-slick--satellite" d="M333 375 C389 337 444 357 484 327 C526 296 580 318 621 306 C666 294 710 321 694 355 C676 391 622 375 588 400 C546 431 495 408 452 424 C408 440 351 421 333 394Z" />
            <g className="illustration-tanker-track">
              <g className="illustration-tanker" filter="url(#sceneShadow)" transform="translate(760 92)">
                <path d="M18 70 L64 19 L300 19 L347 69 L310 112 L69 112 Z" fill="#e34f43" />
                <path d="M53 67 L83 32 L284 32 L316 68 L288 94 L78 94 Z" fill="url(#tankerDeck)" />
                <rect x="88" y="42" width="62" height="42" rx="4" fill="#f8fcfd" />
                <rect x="98" y="51" width="12" height="12" fill="#17617a" /><rect x="115" y="51" width="12" height="12" fill="#17617a" /><rect x="132" y="51" width="10" height="12" fill="#17617a" />
                <rect x="201" y="39" width="51" height="38" rx="5" fill="#d94a40" /><rect x="259" y="42" width="23" height="32" rx="4" fill="#f7d55c" />
                <path d="M116 40 V4 M103 14 H129 M110 4 H122" stroke="#f8fcfd" strokeWidth="6" strokeLinecap="round" />
              </g>
            </g>
            <path className="illustration-discharge" d="M804 236 C728 267 697 310 653 335 C610 359 567 359 528 378" />
            <g className="illustration-response illustration-response--one" transform="translate(155 425) rotate(-7)"><path d="M0 35 L28 3 H112 L139 34 L110 63 H28Z" fill="#f4f8fa" /><path d="M22 48 H117 L106 65 H35Z" fill="#ec6a4d" /><rect x="45" y="12" width="40" height="28" rx="3" fill="#eaf8fa" /><rect x="53" y="18" width="12" height="10" fill="#23718a" /><rect x="68" y="18" width="12" height="10" fill="#23718a" /></g>
            <g className="illustration-response illustration-response--two" transform="translate(845 430) rotate(5)"><path d="M0 35 L28 3 H112 L139 34 L110 63 H28Z" fill="#f4f8fa" /><path d="M22 48 H117 L106 65 H35Z" fill="#4753a0" /><rect x="45" y="12" width="40" height="28" rx="3" fill="#eaf8fa" /><rect x="53" y="18" width="12" height="10" fill="#23718a" /><rect x="68" y="18" width="12" height="10" fill="#23718a" /></g>
            <path className="illustration-boom" d="M195 453 C290 518 450 537 626 511 S930 468 1014 441" />
            <g className="illustration-label" transform="translate(310 516)"><circle r="5" /><text x="14" y="4">CONTAINMENT PERIMETER</text></g>
            <g className="illustration-label illustration-label--alert" transform="translate(482 288)"><circle r="5" /><text x="14" y="4">DETECTED OIL SLICK</text></g>
            <rect width="1200" height="620" fill="url(#seaGlow)" opacity=".24" />
          </svg>
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

        <div className="role-launcher" id="role-access">
          <div className="role-launcher__heading">
            <div><p className="eyebrow">Choose a workspace</p><h2>Continue with your operational role</h2></div>
            <span>{developmentMode ? "Demo access" : "Secure access"}</span>
          </div>
          <div className="role-launcher__grid">{accounts.map((account) => {
            const Icon = account.icon;
            const selected = selectedRole === account.role;
            return <button type="button" key={account.role} onClick={() => chooseRole(account)} className={selected ? "selected" : ""} aria-pressed={selected}>
              <div className="role-launcher__icon"><Icon size={21} /></div>
              <span><strong>{account.label} Login</strong><small>{account.description}</small></span>
              <ArrowRight size={18} />
            </button>;
          })}</div>
        </div>
        <div className="auth-security" id="security"><ShieldCheck size={15} /><span><strong>Enterprise-ready access</strong> Password hashing · expiring sessions · server-enforced permissions</span></div>
      </section>

      {loginOpen && <section className="auth-panel" role="dialog" aria-modal="true" aria-labelledby="auth-dialog-title">
      <button className="auth-panel__backdrop" type="button" aria-label="Close sign in" onClick={() => setLoginOpen(false)} />
      <div className="auth-card">
        <button className="auth-card__close" type="button" aria-label="Close sign in" onClick={() => setLoginOpen(false)}><X size={18} /></button>
        <div className="auth-card__top">
          <div className="auth-card__icon">{selectedAccount ? (() => { const Icon = selectedAccount.icon; return <Icon size={22} />; })() : <ShieldCheck size={22} />}</div>
          <span><LockKeyhole size={12} /> Secure access</span>
        </div>
        <p className="eyebrow">Identity verification</p>
        <h2 id="auth-dialog-title">{selectedAccount ? `${selectedAccount.label} sign in` : "Sign in to SeaScan"}</h2>
        <p className="auth-card__intro">{selectedAccount?.description ?? "Use your assigned operational account."}</p>
        <form onSubmit={(event) => void submit(event)}>
          <label><span>Username</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Enter username" required /></label>
          <label><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter password" minLength={8} required /></label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? "Verifying identity…" : <>Enter secure workspace <ArrowRight size={16} /></>}</button>
        </form>
        {developmentMode && <p className="auth-demo-note"><CheckCircle2 size={14} /> Demo credentials filled automatically when you select a role.</p>}
      </div>
      </section>}
    </section>
  </main>;
}
