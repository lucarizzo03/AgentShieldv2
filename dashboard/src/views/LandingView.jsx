import { Link } from "react-router-dom";
import { useState } from "react";

const CODE_PYTHON = `pip install agentshield-pythonv2`;

const CODE_USAGE = `from agentshield import AgentShield, SpendRequest

client = AgentShield(
    agent_id="agt_...",
    hmac_secret="sk_live_...",
    base_url="https://api.agentshield.dev",
)

result = client.spend_request(SpendRequest(
    agent_id="agt_...",
    declared_goal="Book flight JFK to LAX",
    amount_cents=25000,
    currency="USD",
    vendor_url_or_name="delta.com",
    item_description="Economy seat JFK-LAX, Oct 12",
    asset_type="FIAT",
    destination_address="0x742d35...",
))

print(result.verdict)  # SAFE | SUSPICIOUS | MALICIOUS`;

const CODE_CURL = `curl -X POST https://api.agentshield.dev/v1/spend-request \\
  -H "Content-Type: application/json" \\
  -H "x-agent-id: agt_..." \\
  -H "x-timestamp: 2026-05-18T12:00:00Z" \\
  -H "x-signature: sha256=<hmac>" \\
  -d '{
    "agent_id": "agt_...",
    "declared_goal": "Book flight JFK to LAX",
    "amount_cents": 25000,
    "vendor_url_or_name": "delta.com",
    "asset_type": "FIAT",
    "destination_address": "0x742d35..."
  }'`;

const verdicts = [
  {
    code: "200",
    label: "SAFE",
    color: "#00C853",
    bg: "rgba(0,200,83,0.08)",
    border: "rgba(0,200,83,0.2)",
    desc: "Agent is cleared to proceed with the payment.",
  },
  {
    code: "202",
    label: "SUSPICIOUS",
    color: "#FF9500",
    bg: "rgba(255,149,0,0.08)",
    border: "rgba(255,149,0,0.2)",
    desc: "Held for human review. Agent must wait for a decision.",
  },
  {
    code: "403",
    label: "MALICIOUS",
    color: "#FF3B30",
    bg: "rgba(255,59,48,0.08)",
    border: "rgba(255,59,48,0.2)",
    desc: "Blocked. The agent should not retry this request.",
  },
];

const checks = [
  {
    id: "A",
    label: "Quantitative",
    where: "Redis",
    desc: "Daily budget, loop detection, destination burst — enforced atomically with Lua.",
  },
  {
    id: "B",
    label: "Policy",
    where: "Postgres",
    desc: "Vendor blocklist, amount thresholds, stablecoin and network allowlists.",
  },
  {
    id: "C",
    label: "Semantic",
    where: "Claude Haiku",
    desc: "Does the stated goal actually match what's being purchased?",
  },
  {
    id: "D",
    label: "Goal Drift",
    where: "Claude Haiku",
    desc: "Is this purchase within what the agent is supposed to do at all?",
  },
];

const features = [
  { label: "Idempotency", desc: "Cache verdicts 24 h to prevent double-charges on retries." },
  { label: "HMAC signing", desc: "Every request is payload-signed — identity + integrity, not just auth." },
  { label: "HITL flow", desc: "Suspicious requests pause the agent and queue for human review." },
  { label: "Audit log", desc: "Append-only ledger of every decision, forever." },
  { label: "Callback URL", desc: "Push the resolution to your agent the moment a human decides." },
  { label: "SSRF protection", desc: "Callback URLs are validated against public IPs only." },
];

function Tab({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "transparent",
        border: "none",
        borderBottom: active ? "1px solid #ededed" : "1px solid transparent",
        color: active ? "#ededed" : "#666",
        fontFamily: "Geist Mono, IBM Plex Mono, monospace",
        fontSize: 12,
        padding: "6px 0",
        marginRight: 20,
        cursor: "pointer",
        letterSpacing: "0.05em",
      }}
    >
      {children}
    </button>
  );
}

export default function LandingView() {
  const [codeTab, setCodeTab] = useState("python");

  const activeCode = codeTab === "python" ? CODE_USAGE : CODE_CURL;

  return (
    <div style={{ background: "#0c0c0c", color: "#ededed", fontFamily: "Geist, IBM Plex Sans, sans-serif", minHeight: "100vh" }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::selection { background: rgba(237,237,237,0.15); }
        .mono { font-family: "Geist Mono", "IBM Plex Mono", monospace; }
        .landing-link { color: #888; text-decoration: none; font-size: 13px; transition: color 120ms; }
        .landing-link:hover { color: #ededed; }
        .btn-primary {
          display: inline-block;
          background: #ededed;
          color: #0c0c0c;
          border: 1px solid #ededed;
          padding: 10px 20px;
          font-size: 13px;
          font-family: "Geist Mono", monospace;
          letter-spacing: 0.02em;
          cursor: pointer;
          text-decoration: none;
          transition: opacity 120ms;
        }
        .btn-primary:hover { opacity: 0.88; }
        .btn-ghost {
          display: inline-block;
          background: transparent;
          color: #ededed;
          border: 1px solid #333;
          padding: 10px 20px;
          font-size: 13px;
          font-family: "Geist Mono", monospace;
          letter-spacing: 0.02em;
          cursor: pointer;
          text-decoration: none;
          transition: border-color 120ms;
        }
        .btn-ghost:hover { border-color: #555; }
        .check-card {
          border: 1px solid #1e1e1e;
          background: #111;
          padding: 20px;
          transition: border-color 120ms;
        }
        .check-card:hover { border-color: #2a2a2a; }
        .feature-item {
          padding: 16px 0;
          border-bottom: 1px solid #1a1a1a;
          display: grid;
          grid-template-columns: 160px 1fr;
          gap: 12px;
        }
        .feature-item:last-child { border-bottom: none; }
        @media (max-width: 640px) {
          .feature-item { grid-template-columns: 1fr; gap: 4px; }
          .verdict-grid { grid-template-columns: 1fr !important; }
          .check-grid { grid-template-columns: 1fr 1fr !important; }
          .hero-ctas { flex-direction: column !important; align-items: flex-start !important; }
        }
      `}</style>

      {/* Nav */}
      <nav style={{ borderBottom: "1px solid #1a1a1a", padding: "0 32px", height: 52, display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, background: "rgba(12,12,12,0.9)", backdropFilter: "blur(8px)", zIndex: 10 }}>
        <span className="mono" style={{ fontSize: 13, color: "#ededed", letterSpacing: "0.06em" }}>AGENTSHIELD</span>
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="landing-link">GitHub</a>
          <a href="#how-it-works" className="landing-link">How it works</a>
          <a href="#integrate" className="landing-link">Integrate</a>
          <Link to="/auth" className="btn-primary" style={{ padding: "6px 14px", fontSize: 12 }}>Sign in</Link>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ maxWidth: 860, margin: "0 auto", padding: "96px 32px 80px" }}>
        <div className="mono" style={{ fontSize: 11, color: "#555", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 20 }}>
          Spending firewall for AI agents
        </div>
        <h1 style={{ fontSize: "clamp(2.2rem, 5.5vw, 3.8rem)", fontWeight: 600, lineHeight: 1.1, letterSpacing: "-0.02em", maxWidth: 680, marginBottom: 20 }}>
          Your AI agents need a spending policy.
        </h1>
        <p style={{ fontSize: 17, color: "#888", lineHeight: 1.65, maxWidth: 540, marginBottom: 36 }}>
          Before an agent executes a payment, it asks AgentShield. Four checks run in under 200 ms — budget, policy, semantics, and goal drift. You get back one of three answers.
        </p>

        {/* Verdict pills */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 36 }}>
          {verdicts.map((v) => (
            <span
              key={v.label}
              className="mono"
              style={{ fontSize: 11, padding: "4px 10px", border: `1px solid ${v.border}`, background: v.bg, color: v.color, letterSpacing: "0.06em" }}
            >
              {v.code} {v.label}
            </span>
          ))}
        </div>

        <div className="hero-ctas" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link to="/auth" className="btn-primary">Get Started →</Link>
          <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="btn-ghost">View GitHub</a>
        </div>
      </section>

      {/* Divider */}
      <div style={{ borderTop: "1px solid #1a1a1a" }} />

      {/* How it works */}
      <section id="how-it-works" style={{ maxWidth: 860, margin: "0 auto", padding: "72px 32px" }}>
        <div className="mono" style={{ fontSize: 11, color: "#555", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10 }}>
          How it works
        </div>
        <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2rem)", fontWeight: 600, letterSpacing: "-0.015em", marginBottom: 12 }}>
          Four checks. One verdict.
        </h2>
        <p style={{ color: "#666", fontSize: 15, marginBottom: 40, lineHeight: 1.6 }}>
          Checks A and B run sequentially. If either hard-denies, C and D are skipped entirely — no Claude API call is made. C and D run in parallel only when A and B both pass.
        </p>

        <div className="check-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {checks.map((c) => (
            <div key={c.id} className="check-card">
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12 }}>
                <span className="mono" style={{ fontSize: 11, color: "#444", letterSpacing: "0.1em" }}>CHECK {c.id}</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 4 }}>{c.label}</div>
              <div className="mono" style={{ fontSize: 11, color: "#555", marginBottom: 10 }}>{c.where}</div>
              <div style={{ fontSize: 13, color: "#777", lineHeight: 1.55 }}>{c.desc}</div>
            </div>
          ))}
        </div>

        {/* Verdict cards */}
        <div className="verdict-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 32 }}>
          {verdicts.map((v) => (
            <div key={v.label} style={{ border: `1px solid ${v.border}`, background: v.bg, padding: "18px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span className="mono" style={{ fontSize: 10, color: "#555" }}>{v.code}</span>
                <span className="mono" style={{ fontSize: 12, color: v.color, letterSpacing: "0.06em" }}>{v.label}</span>
              </div>
              <p style={{ fontSize: 13, color: "#888", lineHeight: 1.5 }}>{v.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Divider */}
      <div style={{ borderTop: "1px solid #1a1a1a" }} />

      {/* Code integration */}
      <section id="integrate" style={{ maxWidth: 860, margin: "0 auto", padding: "72px 32px" }}>
        <div className="mono" style={{ fontSize: 11, color: "#555", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10 }}>
          Integrate
        </div>
        <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2rem)", fontWeight: 600, letterSpacing: "-0.015em", marginBottom: 12 }}>
          Add a firewall in minutes.
        </h2>
        <p style={{ color: "#666", fontSize: 15, marginBottom: 32, lineHeight: 1.6 }}>
          Install the SDK, create an agent in the dashboard, and wrap any payment call. That's it.
        </p>

        {/* Install step */}
        <div style={{ marginBottom: 16 }}>
          <div className="mono" style={{ fontSize: 11, color: "#444", letterSpacing: "0.1em", marginBottom: 8 }}>1 · INSTALL</div>
          <div style={{ background: "#111", border: "1px solid #1e1e1e", padding: "14px 18px" }}>
            <pre className="mono" style={{ fontSize: 13, color: "#ededed", lineHeight: 1.5 }}>
              <span style={{ color: "#555" }}>$ </span>{CODE_PYTHON}
            </pre>
          </div>
        </div>

        {/* Usage step */}
        <div>
          <div className="mono" style={{ fontSize: 11, color: "#444", letterSpacing: "0.1em", marginBottom: 8 }}>2 · CALL THE FIREWALL</div>
          <div style={{ background: "#111", border: "1px solid #1e1e1e" }}>
            <div style={{ borderBottom: "1px solid #1a1a1a", padding: "10px 18px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Tab active={codeTab === "python"} onClick={() => setCodeTab("python")}>Python</Tab>
                <Tab active={codeTab === "curl"} onClick={() => setCodeTab("curl")}>cURL</Tab>
              </div>
            </div>
            <div style={{ padding: "18px 20px", overflowX: "auto" }}>
              <pre className="mono" style={{ fontSize: 12.5, color: "#ccc", lineHeight: 1.65, whiteSpace: "pre" }}>{activeCode}</pre>
            </div>
          </div>
        </div>

        {/* Response preview */}
        <div style={{ marginTop: 16, background: "#111", border: "1px solid #1e1e1e" }}>
          <div style={{ borderBottom: "1px solid #1a1a1a", padding: "10px 18px" }}>
            <span className="mono" style={{ fontSize: 11, color: "#444", letterSpacing: "0.1em" }}>RESPONSE</span>
          </div>
          <div style={{ padding: "18px 20px" }}>
            <pre className="mono" style={{ fontSize: 12.5, color: "#ccc", lineHeight: 1.65 }}>{`{
  "verdict": "SAFE",
  "status": "APPROVED_EXECUTED",
  "request_id": "req_01JW...",
  "approved_amount_cents": 25000,
  "reasons": [
    "BUDGET_WITHIN_LIMIT",
    "VENDOR_ALLOWED",
    "SEMANTIC_ALIGNMENT_HIGH",
    "GOAL_WITHIN_SCOPE"
  ],
  "agent_feedback": {
    "check_a_quantitative": { "passed": true },
    "check_b_policy":       { "passed": true },
    "check_c_semantic":     { "alignment_label": "ALIGNED", "risk_score": 12 },
    "check_d_goal_drift":   { "within_scope": true, "matched_scope": "travel booking" }
  }
}`}</pre>
          </div>
        </div>
      </section>

      {/* Divider */}
      <div style={{ borderTop: "1px solid #1a1a1a" }} />

      {/* Features */}
      <section style={{ maxWidth: 860, margin: "0 auto", padding: "72px 32px" }}>
        <div className="mono" style={{ fontSize: 11, color: "#555", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10 }}>
          Built-in
        </div>
        <h2 style={{ fontSize: "clamp(1.5rem, 3vw, 2rem)", fontWeight: 600, letterSpacing: "-0.015em", marginBottom: 32 }}>
          Everything you need, nothing you don't.
        </h2>
        <div>
          {features.map((f) => (
            <div key={f.label} className="feature-item">
              <div style={{ fontSize: 13, fontWeight: 500, color: "#ccc" }}>{f.label}</div>
              <div style={{ fontSize: 13, color: "#666", lineHeight: 1.55 }}>{f.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Divider */}
      <div style={{ borderTop: "1px solid #1a1a1a" }} />

      {/* CTA */}
      <section style={{ maxWidth: 860, margin: "0 auto", padding: "80px 32px 96px", textAlign: "center" }}>
        <div className="mono" style={{ fontSize: 11, color: "#00C853", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 16 }}>
          ● Live
        </div>
        <h2 style={{ fontSize: "clamp(1.8rem, 4vw, 2.8rem)", fontWeight: 600, letterSpacing: "-0.02em", marginBottom: 16 }}>
          Start protecting your agents.
        </h2>
        <p style={{ color: "#666", fontSize: 15, marginBottom: 36, maxWidth: 440, margin: "0 auto 36px" }}>
          Create an account, spin up an agent, and make your first protected spend request in under five minutes.
        </p>
        <Link to="/auth" className="btn-primary">Get Started →</Link>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #1a1a1a", padding: "20px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <span className="mono" style={{ fontSize: 11, color: "#333", letterSpacing: "0.06em" }}>AGENTSHIELD</span>
        <div style={{ display: "flex", gap: 24 }}>
          <a href="https://github.com/lucarizzo03/AgentShieldv2" target="_blank" rel="noreferrer" className="landing-link">GitHub</a>
          <a href="mailto:rizzoluca2003@gmail.com" className="landing-link">Contact</a>
          <Link to="/auth" className="landing-link">Sign in</Link>
        </div>
      </footer>
    </div>
  );
}
