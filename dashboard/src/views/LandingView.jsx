import { Link } from "react-router-dom";
import { useState } from "react";

// ─── Syntax token colors ────────────────────────────────────────────────────
const T = {
  kw:    "#4FC1FF", // keywords
  cls:   "#56D364", // class names / types
  str:   "#CE9178", // strings
  num:   "#B5CEA8", // numbers
  cmt:   "#4D5566", // comments
  fn:    "#DCDCAA", // function calls
  key:   "#9CDCFE", // kwarg / json keys
  def:   "#C8C8C8", // default
  op:    "#808080", // operators / punctuation
};

// One row in a code block. Line number + a single pre-wrapped span so tokens
// stay inline and leading spaces are preserved without flex oddities.
function CodeRow({ segs, lineNum, showLineNum = true }) {
  return (
    <div style={{ display: "flex", lineHeight: 1.65, minHeight: "1.65em" }}>
      {showLineNum && (
        <span style={{ minWidth: 30, color: "#2e2e2e", userSelect: "none", textAlign: "right", marginRight: 16, flexShrink: 0 }}>
          {segs ? lineNum : ""}
        </span>
      )}
      <span style={{ whiteSpace: "pre" }}>
        {segs
          ? segs.map(([text, tok], i) => <span key={i} style={{ color: T[tok] || T.def }}>{text}</span>)
          : null}
      </span>
    </div>
  );
}

// ─── Python usage code ───────────────────────────────────────────────────────
const PYTHON = [
  [["from ", "kw"], ["agentshield ", "def"], ["import ", "kw"], ["AgentShield", "cls"], [", ", "op"], ["SpendRequest", "cls"]],
  null,
  [["client", "def"], [" = ", "op"], ["AgentShield", "cls"], ["(", "op"]],
  [["    agent_id", "key"], ["=", "op"], ['"agt_..."', "str"], [",", "op"]],
  [["    hmac_secret", "key"], ["=", "op"], ['"sk_live_..."', "str"], [",", "op"]],
  [["    base_url", "key"], ["=", "op"], ['"https://agentshieldv2-backend-production.up.railway.app"', "str"], [",", "op"]],
  [[")", "op"]],
  null,
  [["result", "def"], [" = ", "op"], ["client", "def"], [".", "op"], ["spend_request", "fn"], ["(", "op"], ["SpendRequest", "cls"], ["(", "op"]],
  [["    agent_id", "key"], ["=", "op"], ['"agt_..."', "str"], [",", "op"]],
  [["    declared_goal", "key"], ["=", "op"], ['"Book flight JFK to LAX"', "str"], [",", "op"]],
  [["    amount_cents", "key"], ["=", "op"], ["25000", "num"], [",", "op"]],
  [["    vendor_url_or_name", "key"], ["=", "op"], ['"delta.com"', "str"], [",", "op"]],
  [["    asset_type", "key"], ["=", "op"], ['"FIAT"', "str"], [",", "op"]],
  [["    destination_address", "key"], ["=", "op"], ['"0x742d35..."', "str"], [",", "op"]],
  [["))", "op"]],
  null,
  [["print", "fn"], ["(", "op"], ["result", "def"], [".", "op"], ["verdict", "key"], [")", "op"], ["   ", "def"], ["# SAFE | SUSPICIOUS | MALICIOUS", "cmt"]],
];

// ─── Hero terminal (shorter, self-contained) ─────────────────────────────────
const HERO_LINES = [
  [["from ", "kw"], ["agentshield ", "def"], ["import ", "kw"], ["AgentShield", "cls"], [", ", "op"], ["SpendRequest", "cls"]],
  null,
  [["shield", "def"], [" = ", "op"], ["AgentShield", "cls"], ["(", "op"]],
  [["    agent_id", "key"], ["=", "op"], ['"agt_..."', "str"], [",", "op"]],
  [["    hmac_secret", "key"], ["=", "op"], ['"sk_live_..."', "str"], [",", "op"]],
  [[")", "op"]],
  null,
  [["result", "def"], [" = ", "op"], ["shield", "def"], [".", "op"], ["spend_request", "fn"], ["(", "op"], ["SpendRequest", "cls"], ["(", "op"]],
  [["    declared_goal", "key"], ["=", "op"], ['"Book flight JFK to LAX"', "str"], [",", "op"]],
  [["    amount_cents", "key"], ["=", "op"], ["25000", "num"], [",", "op"]],
  [["    vendor_url_or_name", "key"], ["=", "op"], ['"delta.com"', "str"], [",", "op"]],
  [["))", "op"]],
  null,
  [["print", "fn"], ["(result.", "op"], ["verdict", "key"], [")   ", "op"], ["# SAFE | SUSPICIOUS | MALICIOUS", "cmt"]],
];

// ─── cURL code ───────────────────────────────────────────────────────────────
const CURL = [
  [["curl", "fn"], [" -X ", "op"], ["POST", "str"], [" \\", "op"]],
  [["  https://api.agentshield.dev/v1/spend-request", "def"], [" \\", "op"]],
  [["  -H ", "op"], ['"Content-Type: application/json"', "str"], [" \\", "op"]],
  [["  -H ", "op"], ['"x-agent-id: agt_..."', "str"], [" \\", "op"]],
  [["  -H ", "op"], ['"x-timestamp: 2026-05-18T12:00:00Z"', "str"], [" \\", "op"]],
  [["  -H ", "op"], ['"x-signature: sha256=<hmac>"', "str"], [" \\", "op"]],
  [["  -d ", "op"], ["'{", "str"]],
  [["    ", "def"], ['"agent_id"', "key"], [":  ", "op"], ['"agt_..."', "str"], [",", "op"]],
  [["    ", "def"], ['"declared_goal"', "key"], [":  ", "op"], ['"Book flight JFK to LAX"', "str"], [",", "op"]],
  [["    ", "def"], ['"amount_cents"', "key"], [":  ", "op"], ["25000", "num"], [",", "op"]],
  [["    ", "def"], ['"vendor_url_or_name"', "key"], [":  ", "op"], ['"delta.com"', "str"], [",", "op"]],
  [["    ", "def"], ['"asset_type"', "key"], [":  ", "op"], ['"FIAT"', "str"]],
  [["  }'", "str"]],
];

// ─── Response preview ────────────────────────────────────────────────────────
const RESPONSE = [
  [["{", "op"]],
  [["  ", "def"], ['"verdict"', "key"], [": ", "op"], ['"SAFE"', "str"], [",", "op"]],
  [["  ", "def"], ['"status"', "key"], [": ", "op"], ['"APPROVED_EXECUTED"', "str"], [",", "op"]],
  [["  ", "def"], ['"request_id"', "key"], [": ", "op"], ['"req_01JW..."', "str"], [",", "op"]],
  [["  ", "def"], ['"approved_amount_cents"', "key"], [": ", "op"], ["25000", "num"], [",", "op"]],
  [["  ", "def"], ['"agent_feedback"', "key"], [": {", "op"]],
  [["    ", "def"], ['"check_a_quantitative"', "key"], [": { ", "op"], ['"passed"', "key"], [": ", "op"], ["true", "kw"], [" },", "op"]],
  [["    ", "def"], ['"check_b_policy"', "key"], [":       { ", "op"], ['"passed"', "key"], [": ", "op"], ["true", "kw"], [" },", "op"]],
  [["    ", "def"], ['"check_c_semantic"', "key"], [":     { ", "op"], ['"alignment_label"', "key"], [": ", "op"], ['"ALIGNED"', "str"], [", ", "op"], ['"risk_score"', "key"], [": ", "op"], ["12", "num"], [" },", "op"]],
  [["    ", "def"], ['"check_d_goal_drift"', "key"], [":  { ", "op"], ['"within_scope"', "key"], [": ", "op"], ["true", "kw"], [", ", "op"], ['"matched_scope"', "key"], [": ", "op"], ['"travel booking"', "str"], [" }", "op"]],
  [["  }", "op"]],
  [["}", "op"]],
];

const verdicts = [
  { code: "200", label: "SAFE",       desc: "Cleared. Agent may proceed." },
  { code: "202", label: "SUSPICIOUS", desc: "Held. Human review required." },
  { code: "403", label: "MALICIOUS",  desc: "Blocked. Do not retry." },
];

const checks = [
  { id: "A", label: "Quantitative", where: "Redis",        desc: "Budget limits, loop detection, and destination burst — enforced atomically via Lua script." },
  { id: "B", label: "Policy",       where: "Postgres",     desc: "Vendor blocklist, per-transaction thresholds, network and stablecoin allowlists." },
  { id: "C", label: "Semantic",     where: "Claude Haiku", desc: "Does the stated goal actually match what's being purchased?" },
  { id: "D", label: "Goal Drift",   where: "Claude Haiku", desc: "Is this purchase within what the agent is supposed to do at all?" },
];

const features = [
  { label: "Idempotency",      desc: "24h verdict cache prevents double-charges on network retries." },
  { label: "HMAC signing",     desc: "Every request is payload-signed — identity and integrity, not just a key." },
  { label: "HITL queue",       desc: "Suspicious requests pause the agent and surface in a dashboard approval queue." },
  { label: "Append-only log",  desc: "Every decision is recorded. No updates, no deletes, ever." },
  { label: "Callback URL",     desc: "Push the human decision to your agent the moment it's resolved." },
  { label: "SSRF protection",  desc: "Callback URLs are validated against public IPs only — RFC-1918 blocked." },
];

function Tab({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "transparent", border: "none",
        borderBottom: active ? "1px solid #ededed" : "1px solid transparent",
        color: active ? "#ededed" : "#555",
        fontFamily: "Geist Mono, IBM Plex Mono, monospace",
        fontSize: 11, letterSpacing: "0.06em",
        padding: "6px 0", marginRight: 18, cursor: "pointer",
        transition: "color 120ms",
      }}
    >
      {children}
    </button>
  );
}

function CodeWindow({ title, children, style }) {
  return (
    <div style={{ border: "1px solid #1e1e1e", background: "#0e0e0e", ...style }}>
      <div style={{ borderBottom: "1px solid #1e1e1e", padding: "9px 14px", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#333" }} />
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#333" }} />
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#333" }} />
        {title ? <span style={{ marginLeft: 8, fontFamily: "Geist Mono, monospace", fontSize: 11, color: "#444", letterSpacing: "0.05em" }}>{title}</span> : null}
      </div>
      {children}
    </div>
  );
}

export default function LandingView() {
  const [codeTab, setCodeTab] = useState("python");
  const lines = codeTab === "python" ? PYTHON : CURL;

  return (
    <div style={{ background: "#0c0c0c", color: "#ededed", fontFamily: "Geist, IBM Plex Sans, sans-serif", minHeight: "100vh", position: "relative", overflowX: "hidden" }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::selection { background: rgba(237,237,237,0.12); }

        /* ── Background grid ──────────────────────────────────── */
        .bg-grid {
          position: fixed; inset: 0; pointer-events: none; z-index: 0;
          background-image: radial-gradient(circle, #1c1c1c 1px, transparent 1px);
          background-size: 28px 28px;
          mask-image: radial-gradient(ellipse 80% 80% at 50% 50%, black 40%, transparent 100%);
          -webkit-mask-image: radial-gradient(ellipse 80% 80% at 50% 50%, black 40%, transparent 100%);
        }

        /* ── Animated orbs ──────────────────────────────────────*/
        .orb {
          position: fixed; border-radius: 50%; pointer-events: none; z-index: 0;
          filter: blur(80px);
        }
        .orb-1 {
          width: 600px; height: 600px;
          top: -180px; right: -120px;
          background: radial-gradient(circle, rgba(255,255,255,0.025) 0%, transparent 70%);
          animation: orbDrift1 22s ease-in-out infinite;
        }
        .orb-2 {
          width: 800px; height: 800px;
          bottom: -200px; left: -200px;
          background: radial-gradient(circle, rgba(255,255,255,0.018) 0%, transparent 70%);
          animation: orbDrift2 28s ease-in-out infinite;
        }
        @keyframes orbDrift1 {
          0%,100% { transform: translate(0,0) scale(1); }
          33%      { transform: translate(-40px, 30px) scale(1.06); }
          66%      { transform: translate(25px, -35px) scale(0.94); }
        }
        @keyframes orbDrift2 {
          0%,100% { transform: translate(0,0) scale(1); }
          33%      { transform: translate(50px, -25px) scale(1.08); }
          66%      { transform: translate(-30px, 45px) scale(0.93); }
        }

        /* ── Typography & links ─────────────────────────────────*/
        .mono { font-family: "Geist Mono", "IBM Plex Mono", monospace; }
        .lbl  { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #444; }
        .lnk  { color: #666; text-decoration: none; font-size: 13px; transition: color 100ms; }
        .lnk:hover { color: #ccc; }

        /* ── Buttons ────────────────────────────────────────────*/
        .btn-p {
          display: inline-block; background: #ededed; color: #0c0c0c;
          border: 1px solid #ededed; padding: 10px 22px; font-size: 13px;
          font-family: "Geist Mono", monospace; letter-spacing: 0.02em;
          cursor: pointer; text-decoration: none; transition: opacity 100ms;
        }
        .btn-p:hover { opacity: 0.85; }
        .btn-g {
          display: inline-block; background: transparent; color: #ccc;
          border: 1px solid #2a2a2a; padding: 10px 22px; font-size: 13px;
          font-family: "Geist Mono", monospace; letter-spacing: 0.02em;
          cursor: pointer; text-decoration: none; transition: border-color 100ms, color 100ms;
        }
        .btn-g:hover { border-color: #444; color: #ededed; }

        /* ── Check cards ─────────────────────────────────────────*/
        .check-card {
          border: 1px solid #1a1a1a; background: #0e0e0e; padding: 20px 18px;
          transition: border-color 150ms;
        }
        .check-card:hover { border-color: #2a2a2a; }

        /* ── Feature rows ────────────────────────────────────────*/
        .feat { padding: 14px 0; border-bottom: 1px solid #161616; display: grid; grid-template-columns: 148px 1fr; gap: 16px; }
        .feat:last-child { border-bottom: none; }

        /* ── Code line numbers ───────────────────────────────────*/
        .code-body { padding: 16px 20px; overflow-x: auto; }
        .code-line { display: flex; line-height: 1.65; }
        .ln { min-width: 32px; color: #333; user-select: none; font-size: 12px; text-align: right; margin-right: 16px; flex-shrink: 0; }

        /* ── Responsive ──────────────────────────────────────────*/
        @media (max-width: 700px) {
          .hero-cols { grid-template-columns: 1fr !important; }
          .check-grid { grid-template-columns: 1fr 1fr !important; }
          .verdict-grid { grid-template-columns: 1fr !important; }
          .feat { grid-template-columns: 1fr; gap: 4px; }
        }
        @media (max-width: 480px) {
          .check-grid { grid-template-columns: 1fr !important; }
        }

        /* ── Live dot pulse ──────────────────────────────────────*/
        .dot-live {
          width: 6px; height: 6px; border-radius: 50%; background: #00C853;
          animation: dotPulse 1.1s ease-in-out infinite; flex-shrink: 0;
        }
        @keyframes dotPulse {
          0%,100% { opacity: 0.35; transform: scale(0.8); }
          50%      { opacity: 1;    transform: scale(1);   }
        }

        /* ── Scan line on terminal ────────────────────────────────*/
        @keyframes scan {
          0%   { top: 0; opacity: 0; }
          5%   { opacity: 1; }
          95%  { opacity: 1; }
          100% { top: 100%; opacity: 0; }
        }
      `}</style>

      {/* Background layers */}
      <div className="bg-grid" />
      <div className="orb orb-1" />
      <div className="orb orb-2" />

      {/* Content wrapper */}
      <div style={{ position: "relative", zIndex: 1 }}>

        {/* ── Nav ───────────────────────────────────────────────── */}
        <nav style={{ borderBottom: "1px solid #161616", padding: "0 32px", height: 52, display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, background: "rgba(12,12,12,0.85)", backdropFilter: "blur(12px)", zIndex: 10 }}>
          <span className="mono" style={{ fontSize: 12, color: "#ededed", letterSpacing: "0.08em" }}>AGENTSHIELD</span>
          <div style={{ display: "flex", alignItems: "center", gap: 26 }}>
            <a href="#how-it-works" className="lnk">How it works</a>
            <a href="#integrate" className="lnk">Integrate</a>
            <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="lnk">GitHub</a>
            <Link to="/auth" className="btn-p" style={{ padding: "5px 14px", fontSize: 12 }}>Sign in</Link>
          </div>
        </nav>

        {/* ── Hero ──────────────────────────────────────────────── */}
        <section style={{ maxWidth: 1040, margin: "0 auto", padding: "80px 32px 72px" }}>
          <div className="hero-cols" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}>

            {/* Left: copy */}
            <div>
              <div style={{ display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid #1e1e1e", background: "#111", padding: "4px 10px", marginBottom: 28 }}>
                <span className="dot-live" />
                <span className="mono" style={{ fontSize: 10, color: "#555", letterSpacing: "0.1em" }}>LIVE</span>
              </div>

              <h1 style={{ fontSize: "clamp(2.2rem, 4.5vw, 3.4rem)", fontWeight: 600, lineHeight: 1.06, letterSpacing: "-0.03em", marginBottom: 20 }}>
                Spending Firewall<br />for AI Agents.
              </h1>

              <p style={{ fontSize: 15, color: "#777", lineHeight: 1.7, marginBottom: 28, maxWidth: 420 }}>
                Before an agent executes a payment, it asks AgentShield first. Four checks run in under 200 ms — budget, policy, semantics, goal drift — and you get back one of three answers.
              </p>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 28 }}>
                {verdicts.map((v) => (
                  <span key={v.label} className="mono" style={{ fontSize: 10, padding: "3px 9px", border: "1px solid #2a2a2a", background: "#111", color: "#888", letterSpacing: "0.08em" }}>
                    {v.code} {v.label}
                  </span>
                ))}
              </div>

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Link to="/auth" className="btn-p">Start for free →</Link>
                <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="btn-g">View GitHub</a>
              </div>
            </div>

            {/* Right: terminal mockup */}
            <div style={{ position: "relative" }}>
              <CodeWindow style={{ position: "relative", overflow: "hidden" }}>
                {/* Scan line */}
                <div style={{ position: "absolute", left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(79,193,255,0.15), transparent)", animation: "scan 6s linear infinite", pointerEvents: "none", zIndex: 2 }} />
                <div className="code-body mono" style={{ fontSize: 12 }}>
                  {HERO_LINES.map((segs, i) => (
                    <CodeRow key={i} segs={segs} lineNum={i + 1} showLineNum={false} />
                  ))}
                </div>

                {/* Response badge */}
                <div style={{ borderTop: "1px solid #1e1e1e", padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="mono" style={{ fontSize: 10, color: "#444" }}>RESPONSE</span>
                  <span className="mono" style={{ fontSize: 10, padding: "2px 8px", background: "#161616", border: "1px solid #2a2a2a", color: "#888", letterSpacing: "0.06em" }}>200 SAFE</span>
                </div>
              </CodeWindow>

              {/* Glow under terminal */}
              <div style={{ position: "absolute", bottom: -30, left: "10%", right: "10%", height: 40, background: "rgba(255,255,255,0.03)", filter: "blur(20px)", pointerEvents: "none" }} />
            </div>
          </div>
        </section>

        <div style={{ borderTop: "1px solid #161616" }} />

        {/* ── How it works ──────────────────────────────────────── */}
        <section id="how-it-works" style={{ maxWidth: 1040, margin: "0 auto", padding: "72px 32px" }}>
          <div className="lbl mono" style={{ marginBottom: 10 }}>How it works</div>
          <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2.1rem)", fontWeight: 600, letterSpacing: "-0.018em", marginBottom: 10 }}>Four checks. One verdict.</h2>
          <p style={{ color: "#555", fontSize: 14, marginBottom: 40, lineHeight: 1.65, maxWidth: 560 }}>
            A and B run sequentially. If either hard-denies, C and D are skipped — no Claude API call is made. C and D run in parallel only when A and B both pass.
          </p>

          <div className="check-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 1, border: "1px solid #1a1a1a", marginBottom: 1 }}>
            {checks.map((c) => (
              <div key={c.id} className="check-card" style={{ border: "none", borderRight: "1px solid #1a1a1a" }}>
                <div className="mono lbl" style={{ marginBottom: 14 }}>CHECK {c.id}</div>
                <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 3 }}>{c.label}</div>
                <div className="mono" style={{ fontSize: 11, color: "#3a3a3a", marginBottom: 12 }}>{c.where}</div>
                <div style={{ fontSize: 13, color: "#666", lineHeight: 1.6 }}>{c.desc}</div>
              </div>
            ))}
          </div>

          {/* Pipeline diagram */}
          <div style={{ border: "1px solid #1a1a1a", background: "#0e0e0e", padding: "14px 18px", marginBottom: 24 }}>
            <div className="mono" style={{ fontSize: 11, color: "#333", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ color: "#ccc" }}>A</span>
              <span style={{ color: "#333" }}>→</span>
              <span style={{ color: "#ccc" }}>B</span>
              <span style={{ color: "#333" }}>→</span>
              <span style={{ color: "#555" }}>[if pass]</span>
              <span style={{ color: "#333" }}>→</span>
              <span style={{ color: "#ccc" }}>C</span>
              <span style={{ color: "#444" }}> ∥ </span>
              <span style={{ color: "#ccc" }}>D</span>
              <span style={{ color: "#333" }}>→</span>
              <span style={{ color: "#999" }}>SAFE</span>
              <span style={{ color: "#333" }}> / </span>
              <span style={{ color: "#999" }}>SUSPICIOUS</span>
              <span style={{ color: "#333" }}> / </span>
              <span style={{ color: "#999" }}>MALICIOUS</span>
            </div>
          </div>

          {/* Verdict cards */}
          <div className="verdict-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, border: "1px solid #1a1a1a" }}>
            {verdicts.map((v) => (
              <div key={v.label} style={{ padding: "18px 20px", background: "#0e0e0e", borderRight: "1px solid #1a1a1a" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span className="mono" style={{ fontSize: 10, color: "#333" }}>{v.code}</span>
                  <span className="mono" style={{ fontSize: 12, color: "#aaa", letterSpacing: "0.06em" }}>{v.label}</span>
                </div>
                <p style={{ fontSize: 13, color: "#666", lineHeight: 1.5 }}>{v.desc}</p>
              </div>
            ))}
          </div>
        </section>

        <div style={{ borderTop: "1px solid #161616" }} />

        {/* ── Integrate ─────────────────────────────────────────── */}
        <section id="integrate" style={{ maxWidth: 1040, margin: "0 auto", padding: "72px 32px" }}>
          <div className="lbl mono" style={{ marginBottom: 10 }}>Integrate</div>
          <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2.1rem)", fontWeight: 600, letterSpacing: "-0.018em", marginBottom: 10 }}>Add a firewall in minutes.</h2>
          <p style={{ color: "#555", fontSize: 14, marginBottom: 36, lineHeight: 1.65 }}>
            Start for free, grab your credentials, and wrap any payment call.
          </p>

          <CodeWindow style={{ marginBottom: 12 }}>
            <div style={{ borderBottom: "1px solid #1e1e1e", padding: "8px 14px", display: "flex" }}>
              <Tab active={codeTab === "python"} onClick={() => setCodeTab("python")}>Python SDK</Tab>
              <Tab active={codeTab === "curl"} onClick={() => setCodeTab("curl")}>cURL</Tab>
            </div>
            <div className="code-body mono" style={{ fontSize: 12 }}>
              {lines.map((segs, i) => (
                <CodeRow key={i} segs={segs} lineNum={i + 1} />
              ))}
            </div>
          </CodeWindow>

          <CodeWindow>
            <div style={{ borderBottom: "1px solid #1e1e1e", padding: "8px 14px", display: "flex", alignItems: "center", gap: 10 }}>
              <span className="mono" style={{ fontSize: 10, color: "#333" }}>RESPONSE</span>
              <span className="mono" style={{ fontSize: 10, padding: "2px 8px", background: "#161616", border: "1px solid #2a2a2a", color: "#888" }}>200 SAFE</span>
            </div>
            <div className="code-body mono" style={{ fontSize: 12 }}>
              {RESPONSE.map((segs, i) => (
                <CodeRow key={i} segs={segs} lineNum={i + 1} />
              ))}
            </div>
          </CodeWindow>
        </section>

        <div style={{ borderTop: "1px solid #161616" }} />

        {/* ── Features ──────────────────────────────────────────── */}
        <section style={{ maxWidth: 1040, margin: "0 auto", padding: "72px 32px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48 }}>
            <div>
              <div className="lbl mono" style={{ marginBottom: 10 }}>Built-in</div>
              <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2.1rem)", fontWeight: 600, letterSpacing: "-0.018em", marginBottom: 10 }}>Everything you need.</h2>
              <p style={{ color: "#555", fontSize: 14, lineHeight: 1.65 }}>
                No payment adapters, no SDK lock-in, no magic. AgentShield only decides — yes, wait, or no. The agent is responsible for acting on the verdict.
              </p>
            </div>
            <div>
              {features.map((f) => (
                <div key={f.label} className="feat">
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#bbb" }}>{f.label}</div>
                  <div style={{ fontSize: 13, color: "#555", lineHeight: 1.6 }}>{f.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div style={{ borderTop: "1px solid #161616" }} />

        {/* ── CTA ───────────────────────────────────────────────── */}
        <section style={{ maxWidth: 1040, margin: "0 auto", padding: "88px 32px 96px", textAlign: "center" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 18 }}>
            <span className="dot-live" />
            <span className="mono" style={{ fontSize: 10, letterSpacing: "0.12em", color: "#444" }}>LIVE · SAFE AND MALICIOUS VERDICTS FULLY OPERATIONAL</span>
          </div>
          <h2 style={{ fontSize: "clamp(1.8rem, 4vw, 3rem)", fontWeight: 600, letterSpacing: "-0.025em", marginBottom: 16 }}>
            Start protecting your agents.
          </h2>
          <p style={{ color: "#555", fontSize: 15, marginBottom: 36, maxWidth: 400, margin: "0 auto 36px" }}>
            Create an account, register an agent, and make your first protected request in under five minutes.
          </p>
          <Link to="/auth" className="btn-p">Start for free →</Link>
        </section>

        {/* ── Footer ────────────────────────────────────────────── */}
        <footer style={{ borderTop: "1px solid #161616", padding: "18px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <span className="mono" style={{ fontSize: 11, color: "#2a2a2a", letterSpacing: "0.06em" }}>AGENTSHIELD</span>
          <div style={{ display: "flex", gap: 22 }}>
            <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="lnk">GitHub</a>
            <a href="mailto:rizzoluca2003@gmail.com" className="lnk">Contact</a>
            <Link to="/auth" className="lnk">Sign in</Link>
          </div>
        </footer>

      </div>
    </div>
  );
}
