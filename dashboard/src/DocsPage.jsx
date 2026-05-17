import { useState, useRef, useEffect } from "react";

const SECTIONS = [
  {
    group: "Getting Started",
    items: [
      { id: "overview", label: "Overview" },
      { id: "installation", label: "Installation" },
      { id: "quickstart", label: "Quick Start" },
    ],
  },
  {
    group: "Python SDK",
    items: [
      { id: "authentication", label: "Authentication" },
      { id: "spend-request", label: "Making Requests" },
      { id: "async", label: "Async Support" },
      { id: "error-handling", label: "Error Handling" },
      { id: "admin", label: "Admin API" },
      { id: "stablecoin", label: "Stablecoin Payments" },
    ],
  },
  {
    group: "REST API",
    items: [
      { id: "hmac-signing", label: "HMAC Signing" },
      { id: "rest-spend", label: "POST /spend-request" },
      { id: "verdicts", label: "Responses & Verdicts" },
      { id: "hitl", label: "HITL Flow" },
    ],
  },
];

function CodeBlock({ code, lang = "python", agentId, hmacSecret, apiBase }) {
  const [copied, setCopied] = useState(false);

  const resolved = code
    .replace(/\$\{AGENT_ID\}/g, agentId || "agt_your_agent_id")
    .replace(/\$\{HMAC_SECRET\}/g, hmacSecret || "sk_live_••••••••••••••••")
    .replace(/\$\{API_BASE\}/g, apiBase || "http://localhost:8000/v1");

  function copy() {
    navigator.clipboard.writeText(resolved);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div style={{ position: "relative", borderRadius: 6, overflow: "hidden", border: "1px solid #222", marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#161616", padding: "6px 14px", borderBottom: "1px solid #222" }}>
        <span style={{ fontSize: 11, color: "#555", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{lang}</span>
        <button
          onClick={copy}
          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: copied ? "var(--green)" : "#555", fontFamily: "var(--font-mono)", padding: 0, transition: "color 0.15s" }}
        >
          {copied ? "copied!" : "copy"}
        </button>
      </div>
      <pre style={{ margin: 0, padding: "16px 14px", background: "#0d0d0d", fontSize: 12, fontFamily: "var(--font-mono)", color: "#e0e0e0", overflowX: "auto", lineHeight: 1.65 }}>
        <code>{resolved}</code>
      </pre>
    </div>
  );
}

function InlineCode({ children }) {
  return (
    <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 3, padding: "1px 5px", color: "#e0e0e0" }}>
      {children}
    </code>
  );
}

function SectionHeader({ id, children }) {
  return (
    <h2 id={id} style={{ fontSize: 20, fontWeight: 600, color: "#ededed", marginTop: 48, marginBottom: 12, paddingTop: 8, scrollMarginTop: 24 }}>
      {children}
    </h2>
  );
}

function SubHeader({ children }) {
  return (
    <h3 style={{ fontSize: 14, fontWeight: 600, color: "#ededed", marginTop: 28, marginBottom: 8 }}>
      {children}
    </h3>
  );
}

function P({ children, style }) {
  return (
    <p style={{ fontSize: 14, color: "#888", lineHeight: 1.7, marginTop: 0, marginBottom: 12, ...style }}>
      {children}
    </p>
  );
}

function Callout({ color = "amber", children }) {
  const colors = {
    amber: { bg: "rgba(255,149,0,0.07)", border: "#ff9500", text: "#ffb340" },
    blue: { bg: "rgba(10,132,255,0.07)", border: "#0a84ff", text: "#5ac8fa" },
    green: { bg: "rgba(0,200,83,0.07)", border: "#00c853", text: "#30d158" },
  };
  const c = colors[color];
  return (
    <div style={{ background: c.bg, borderLeft: `2px solid ${c.border}`, padding: "10px 14px", borderRadius: "0 4px 4px 0", marginBottom: 16 }}>
      <span style={{ fontSize: 13, color: c.text, lineHeight: 1.6 }}>{children}</span>
    </div>
  );
}

function FieldTable({ rows }) {
  return (
    <div style={{ overflowX: "auto", marginBottom: 20 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["Field", "Type", "Required", "Notes"].map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "7px 12px", borderBottom: "1px solid #222", color: "#555", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([field, type, req, notes], i) => (
            <tr key={field} style={{ background: i % 2 === 0 ? "transparent" : "#0f0f0f" }}>
              <td style={{ padding: "7px 12px", fontFamily: "var(--font-mono)", fontSize: 12, color: "#e0e0e0", borderBottom: "1px solid #1a1a1a" }}>{field}</td>
              <td style={{ padding: "7px 12px", fontFamily: "var(--font-mono)", fontSize: 12, color: "#0a84ff", borderBottom: "1px solid #1a1a1a" }}>{type}</td>
              <td style={{ padding: "7px 12px", fontSize: 12, color: req === "Yes" ? "#00c853" : "#555", borderBottom: "1px solid #1a1a1a" }}>{req}</td>
              <td style={{ padding: "7px 12px", fontSize: 13, color: "#888", borderBottom: "1px solid #1a1a1a" }}>{notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VerdictBadge({ verdict }) {
  const styles = {
    SAFE: { color: "#00c853", bg: "rgba(0,200,83,0.1)", border: "rgba(0,200,83,0.3)" },
    SUSPICIOUS: { color: "#ff9500", bg: "rgba(255,149,0,0.1)", border: "rgba(255,149,0,0.3)" },
    MALICIOUS: { color: "#ff3b30", bg: "rgba(255,59,48,0.1)", border: "rgba(255,59,48,0.3)" },
  };
  const s = styles[verdict];
  return (
    <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 3, background: s.bg, border: `1px solid ${s.border}`, color: s.color, fontFamily: "var(--font-mono)", fontSize: 11, marginRight: 8 }}>
      {verdict}
    </span>
  );
}

export default function DocsPage({ agentId, activeHmac, secretReveal, setSecretReveal, apiBase }) {
  const [activeSection, setActiveSection] = useState("overview");
  const mainRef = useRef(null);
  const programmaticScroll = useRef(false);
  const scrollTimer = useRef(null);

  const hmacDisplay = secretReveal && activeHmac ? activeHmac : "sk_live_••••••••••••••••";

  function scrollToSection(id) {
    const el = document.getElementById(id);
    if (!el) return;
    setActiveSection(id);
    programmaticScroll.current = true;
    clearTimeout(scrollTimer.current);
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    // smooth scroll takes ~600ms; suppress observer updates until it settles
    scrollTimer.current = setTimeout(() => {
      programmaticScroll.current = false;
    }, 700);
  }

  useEffect(() => {
    const container = mainRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (programmaticScroll.current) return;
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        const topmost = visible.reduce((a, b) =>
          a.boundingClientRect.top < b.boundingClientRect.top ? a : b
        );
        setActiveSection(topmost.target.id);
      },
      { root: container, rootMargin: "-10% 0px -65% 0px", threshold: 0 }
    );
    SECTIONS.flatMap((g) => g.items).forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => {
      observer.disconnect();
      clearTimeout(scrollTimer.current);
    };
  }, []);

  const codeProps = { agentId, hmacSecret: hmacDisplay, apiBase };

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* Left sidebar */}
      <div style={{ width: 220, flexShrink: 0, overflowY: "auto", borderRight: "1px solid #1e1e1e", padding: "28px 0" }}>
        <div style={{ padding: "0 20px 20px", borderBottom: "1px solid #1a1a1a", marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: "0.1em" }}>AgentShield</div>
          <div style={{ fontSize: 13, color: "#888", marginTop: 2 }}>Documentation</div>
        </div>
        {SECTIONS.map((group) => (
          <div key={group.group} style={{ marginBottom: 24, padding: "0 12px" }}>
            <div style={{ fontSize: 11, color: "#444", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", padding: "0 8px", marginBottom: 4 }}>
              {group.group}
            </div>
            {group.items.map((item) => {
              const isActive = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => scrollToSection(item.id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "5px 8px", borderRadius: 4, border: "none",
                    background: isActive ? "rgba(255,149,0,0.08)" : "transparent",
                    color: isActive ? "#ff9500" : "#666",
                    fontSize: 13, cursor: "pointer",
                    fontFamily: "var(--font-sans)",
                    transition: "color 0.1s, background 0.1s",
                    borderLeft: isActive ? "2px solid #ff9500" : "2px solid transparent",
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* Main content */}
      <div ref={mainRef} style={{ flex: 1, overflowY: "auto", padding: "40px 60px" }}>
        <div style={{ maxWidth: 760 }}>

          {/* Overview */}
          <SectionHeader id="overview">Overview</SectionHeader>
          <P>
            AgentShield is a spending firewall for autonomous AI agents. Before an agent executes a
            payment, it submits a spend intent to the API. The system runs three parallel risk checks
            and returns one of three verdicts.
          </P>
          <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
            <VerdictBadge verdict="SAFE" />
            <VerdictBadge verdict="SUSPICIOUS" />
            <VerdictBadge verdict="MALICIOUS" />
          </div>
          <P>The three checks run in parallel on every request:</P>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 24 }}>
            {[
              ["Quantitative", "Redis", "Daily budgets, transaction loops, destination bursting"],
              ["Policy", "Postgres", "Vendor blocklists, amount thresholds, stablecoin rules"],
              ["Semantic", "Claude Haiku", "LLM alignment between stated goal and actual purchase"],
            ].map(([name, store, desc]) => (
              <div key={name} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 14px", border: "1px solid #1e1e1e", borderRadius: 6, background: "#0d0d0d" }}>
                <div style={{ minWidth: 100 }}>
                  <div style={{ fontSize: 13, color: "#ededed", fontWeight: 500 }}>{name}</div>
                  <div style={{ fontSize: 11, color: "#444", fontFamily: "var(--font-mono)", marginTop: 2 }}>{store}</div>
                </div>
                <div style={{ fontSize: 13, color: "#666", lineHeight: 1.5 }}>{desc}</div>
              </div>
            ))}
          </div>

          {/* Installation */}
          <SectionHeader id="installation">Installation</SectionHeader>
          <P>Install the Python SDK using pip. Python 3.11 or later is required.</P>
          <CodeBlock lang="bash" code={`pip install agentshield`} {...codeProps} />
          <P>Or with uv:</P>
          <CodeBlock lang="bash" code={`uv add agentshield`} {...codeProps} />

          {/* Quick Start */}
          <SectionHeader id="quickstart">Quick Start</SectionHeader>
          <P>The fastest path to your first spend check. Copy your agent ID and HMAC secret from the Agents page.</P>
          <CodeBlock lang="python" code={`from agentshield import AgentShield, SpendRequest

client = AgentShield(
    agent_id="\${AGENT_ID}",
    hmac_secret="\${HMAC_SECRET}",
    base_url="\${API_BASE}",
)

result = client.spend_request(SpendRequest(
    agent_id="\${AGENT_ID}",
    declared_goal="Book a flight from JFK to LAX",
    amount_cents=25000,
    currency="USD",
    vendor_url_or_name="delta.com",
    item_description="Economy seat JFK-LAX, Oct 12",
    asset_type="FIAT",
))

print(result.verdict)   # SAFE | SUSPICIOUS | MALICIOUS
print(result.status_code)  # 200 | 202 | 403`} {...codeProps} />
          <Callout color="blue">
            A <InlineCode>202</InlineCode> response means the request is held for human review — the agent must poll{" "}
            <InlineCode>get_spend_status(request_id)</InlineCode> until resolved.
          </Callout>

          {/* Authentication */}
          <SectionHeader id="authentication">Authentication</SectionHeader>
          <P>
            The SDK authenticates using HMAC-SHA256. Every request is signed with your agent's secret key,
            which proves both identity and payload integrity.
          </P>
          {activeHmac && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", border: "1px solid #1e1e1e", borderRadius: 4, marginBottom: 16, background: "#0d0d0d" }}>
              <span style={{ fontSize: 12, color: "#555" }}>Your HMAC secret:</span>
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: secretReveal ? "#ff9500" : "#333", flex: 1 }}>
                {secretReveal ? activeHmac : "•".repeat(32)}
              </code>
              <button
                onClick={() => setSecretReveal((p) => !p)}
                style={{ border: "none", background: "transparent", color: "#555", fontSize: 11, cursor: "pointer", fontFamily: "var(--font-mono)" }}
              >
                [{secretReveal ? "hide" : "reveal"}]
              </button>
            </div>
          )}
          <P>Credentials can also be provisioned programmatically via the Admin client:</P>
          <CodeBlock lang="python" code={`from agentshield import AgentShieldAdmin, AgentCreateRequest

admin = AgentShieldAdmin(bearer_token="your-auth0-token")
agent = admin.create_agent(AgentCreateRequest(
    agent_name="my-buying-agent",
    daily_spend_limit_usd=500,
    per_transaction_limit_usd=100,
    auto_approve_under_usd=20,
    asset_type="FIAT",
))

print(agent.agent_id)    # agt_...
print(agent.hmac_secret) # sk_live_...`} {...codeProps} />

          {/* Spend Request */}
          <SectionHeader id="spend-request">Making Requests</SectionHeader>
          <P>
            Call <InlineCode>spend_request()</InlineCode> before executing any payment. Pass the{" "}
            <InlineCode>SpendRequest</InlineCode> model with all payment details. The SDK handles signing automatically.
          </P>
          <CodeBlock lang="python" code={`from agentshield import AgentShield, SpendRequest

client = AgentShield(
    agent_id="\${AGENT_ID}",
    hmac_secret="\${HMAC_SECRET}",
)

result = client.spend_request(SpendRequest(
    agent_id="\${AGENT_ID}",
    declared_goal="Purchase cloud compute credits",
    amount_cents=5000,
    currency="USD",
    vendor_url_or_name="aws.amazon.com",
    item_description="EC2 t3.medium 1-month reserved",
    asset_type="FIAT",
    idempotency_key="run-20241012-001",  # optional dedup
))

if result.verdict == "SAFE":
    execute_payment()  # your code — AgentShield cleared it, you execute it
elif result.verdict == "SUSPICIOUS":
    # poll until human resolves
    status = client.get_spend_status(result.request_id)
elif result.verdict == "MALICIOUS":
    raise RuntimeError("Payment blocked by policy")`} {...codeProps} />

          <SubHeader>SpendRequest fields</SubHeader>
          <FieldTable rows={[
            ["agent_id", "str", "Yes", "Your agent identifier"],
            ["declared_goal", "str", "Yes", "Human-readable payment justification"],
            ["amount_cents", "int", "Yes", "Amount in cents, e.g. 2500 = $25.00"],
            ["currency", "str", "Yes", "ISO 3-letter code, e.g. USD"],
            ["vendor_url_or_name", "str", "Yes", "Domain or vendor name"],
            ["item_description", "str", "Yes", "What is being purchased"],
            ["asset_type", "FIAT | STABLECOIN", "Yes", "Payment rail"],
            ["stablecoin_symbol", "str", "If STABLECOIN", "USDC, USDT, etc."],
            ["network", "str", "If STABLECOIN", "base, ethereum, solana, etc."],
            ["destination_address", "str", "If STABLECOIN", "Wallet address"],
            ["idempotency_key", "str", "No", "Deduplication key for retries"],
            ["agent_callback_url", "str", "No", "Webhook for HITL resolution"],
          ]} />

          <SubHeader>Polling for HITL resolution</SubHeader>
          <P>When a request returns <InlineCode>SUSPICIOUS</InlineCode>, poll until the human reviewer resolves it:</P>
          <CodeBlock lang="python" code={`import time

result = client.spend_request(SpendRequest(...))

if result.verdict == "SUSPICIOUS":
    for _ in range(60):       # timeout after ~5 minutes
        time.sleep(5)
        status = client.get_spend_status(result.request_id)
        if status.status != "WAITING_HUMAN":
            if status.status == "APPROVED_BY_HUMAN_EXECUTED":
                print("Human approved — agent cleared to proceed")
            else:
                print("Denied or expired")
            break`} {...codeProps} />

          {/* Async */}
          <SectionHeader id="async">Async Support</SectionHeader>
          <P>
            Use <InlineCode>AsyncAgentShield</InlineCode> for async/await workflows. All methods are
            mirrored from the sync client as coroutines.
          </P>
          <CodeBlock lang="python" code={`from agentshield import AsyncAgentShield, SpendRequest

async def check_spend():
    async with AsyncAgentShield(
        agent_id="\${AGENT_ID}",
        hmac_secret="\${HMAC_SECRET}",
    ) as client:
        result = await client.spend_request(SpendRequest(
            agent_id="\${AGENT_ID}",
            declared_goal="Pay API invoice",
            amount_cents=9900,
            currency="USD",
            vendor_url_or_name="openai.com",
            item_description="GPT-4 usage invoice",
            asset_type="FIAT",
        ))
        return result`} {...codeProps} />

          {/* Error Handling */}
          <SectionHeader id="error-handling">Error Handling</SectionHeader>
          <P>The SDK surfaces distinct exception types for each failure mode.</P>
          <CodeBlock lang="python" code={`from agentshield import (
    AgentShieldBlockedError,   # 403 — hard deny
    AgentShieldAuthError,      # 401/403 — credential issue
    AgentShieldAPIError,       # other 4xx/5xx
    AgentShieldError,          # base class
)

try:
    result = client.spend_request(SpendRequest(...))
except AgentShieldBlockedError:
    # Verdict is MALICIOUS — do not retry
    log.warning("Payment blocked by AgentShield policy")
except AgentShieldAuthError:
    # Rotate credentials and retry
    client.rotate_hmac()
except AgentShieldAPIError as e:
    log.error(f"API error {e.status_code}: {e.message}")`} {...codeProps} />
          <Callout color="amber">
            <InlineCode>SUSPICIOUS</InlineCode> (202) responses are <strong>not</strong> exceptions — they are
            returned as normal <InlineCode>SpendResponse</InlineCode> objects. Only hard errors and
            auth failures raise exceptions.
          </Callout>

          {/* Admin */}
          <SectionHeader id="admin">Admin API</SectionHeader>
          <P>Manage agents programmatically with <InlineCode>AgentShieldAdmin</InlineCode>.</P>
          <CodeBlock lang="python" code={`from agentshield import AgentShieldAdmin, AgentCreateRequest

admin = AgentShieldAdmin(bearer_token="your-auth0-token")

# Create agent
agent = admin.create_agent(AgentCreateRequest(
    agent_name="research-agent",
    daily_spend_limit_usd=200,
    per_transaction_limit_usd=50,
    auto_approve_under_usd=10,
    blocked_vendors=["gambling.com", "casino.io"],
    allowed_networks=["base", "ethereum"],
    asset_type="STABLECOIN",
))

# List all agents
agents = admin.list_agents()

# Rotate HMAC secret (takes effect immediately)
rotated = client.rotate_hmac()
print(rotated.hmac_secret)  # new secret`} {...codeProps} />
          <Callout color="amber">
            HMAC rotation has no grace period. The old secret is invalidated immediately — any
            in-flight signed requests will fail.
          </Callout>

          {/* Stablecoin */}
          <SectionHeader id="stablecoin">Stablecoin Payments</SectionHeader>
          <P>
            When <InlineCode>asset_type="STABLECOIN"</InlineCode>, provide the token symbol, network,
            and destination wallet address.
          </P>
          <CodeBlock lang="python" code={`result = client.spend_request(SpendRequest(
    agent_id="\${AGENT_ID}",
    declared_goal="Pay contractor in USDC",
    amount_cents=50000,
    currency="USD",
    vendor_url_or_name="contractor.eth",
    item_description="Design work invoice #42",
    asset_type="STABLECOIN",
    stablecoin_symbol="USDC",
    network="base",
    destination_address="0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
))`} {...codeProps} />
          <SubHeader>Supported tokens & networks</SubHeader>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            {[
              ["Tokens", ["USDC", "USDT", "USDC.e", "USDC.b"]],
              ["Networks", ["ethereum", "base", "solana", "polygon", "arbitrum", "tempo"]],
            ].map(([label, items]) => (
              <div key={label} style={{ padding: "12px 14px", border: "1px solid #1e1e1e", borderRadius: 6, background: "#0d0d0d" }}>
                <div style={{ fontSize: 11, color: "#555", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>{label}</div>
                {items.map((item) => (
                  <div key={item} style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "#888", padding: "2px 0" }}>{item}</div>
                ))}
              </div>
            ))}
          </div>

          {/* HMAC Signing */}
          <SectionHeader id="hmac-signing">HMAC Signing</SectionHeader>
          <P>
            If calling the REST API directly (without the SDK), you must sign every request with
            HMAC-SHA256. The canonical message is a newline-joined string of five fields.
          </P>
          <CodeBlock lang="python" code={`import hashlib, hmac, json
from datetime import datetime, timezone

body = {"agent_id": "\${AGENT_ID}", "declared_goal": "...", ...}
timestamp = datetime.now(timezone.utc).isoformat()
body_json = json.dumps(body, separators=(",", ":"))
body_hash = hashlib.sha256(body_json.encode()).hexdigest()

canonical = "\\n".join([
    "POST",
    "/v1/spend-request",
    timestamp,
    body_hash,
    "\${AGENT_ID}",
])

signature = hmac.new(
    "\${HMAC_SECRET}".encode(),
    canonical.encode(),
    hashlib.sha256,
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "x-agent-id": "\${AGENT_ID}",
    "x-timestamp": timestamp,
    "x-signature": signature,
}`} {...codeProps} />
          <Callout color="blue">
            Timestamps must be within <strong>±5 minutes</strong> of server time to prevent replay attacks.
          </Callout>

          {/* REST spend */}
          <SectionHeader id="rest-spend">POST /spend-request</SectionHeader>
          <P>Submit a spend intent for evaluation.</P>
          <CodeBlock lang="bash" code={`curl -X POST \${API_BASE}/spend-request \\
  -H "Content-Type: application/json" \\
  -H "x-agent-id: \${AGENT_ID}" \\
  -H "x-timestamp: 2024-10-12T14:00:00Z" \\
  -H "x-signature: <hmac-sha256>" \\
  -d '{
    "agent_id": "\${AGENT_ID}",
    "declared_goal": "Pay SaaS invoice",
    "amount_cents": 9900,
    "currency": "USD",
    "vendor_url_or_name": "stripe.com",
    "item_description": "Monthly subscription",
    "asset_type": "FIAT"
  }'`} {...codeProps} />

          {/* Verdicts */}
          <SectionHeader id="verdicts">Responses & Verdicts</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 24 }}>
            {[
              { verdict: "SAFE", code: "200", desc: "All checks passed. Payment can execute immediately." },
              { verdict: "SUSPICIOUS", code: "202", desc: "At least one check flagged the request. Held for human review. Agent must wait." },
              { verdict: "MALICIOUS", code: "403", desc: "At least one check returned a hard deny. Payment is blocked. Do not retry." },
            ].map(({ verdict, code, desc }) => (
              <div key={verdict} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 14px", border: "1px solid #1e1e1e", borderRadius: 6, background: "#0d0d0d" }}>
                <div style={{ minWidth: 110 }}>
                  <VerdictBadge verdict={verdict} />
                </div>
                <div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "#555", marginRight: 8 }}>HTTP {code}</span>
                  <span style={{ fontSize: 13, color: "#666" }}>{desc}</span>
                </div>
              </div>
            ))}
          </div>

          {/* HITL */}
          <SectionHeader id="hitl">HITL Flow</SectionHeader>
          <P>
            When a request is flagged as <InlineCode>SUSPICIOUS</InlineCode>, it enters the Human-in-the-Loop
            review queue. The agent receives a <InlineCode>202</InlineCode> and must not proceed with
            payment until the request is resolved.
          </P>
          <div style={{ display: "flex", flexDirection: "column", gap: 0, marginBottom: 24, borderLeft: "1px solid #222", paddingLeft: 16 }}>
            {[
              ["202 received", "Agent gets next_action: AGENT_MUST_WAIT and a request_id."],
              ["Review opens", "A notification appears in the Approvals tab for the human reviewer."],
              ["Human decides", "Reviewer approves or denies via the dashboard or email link."],
              ["Resolution", "APPROVE → agent cleared to proceed. DENY or expiry (10 min) → blocked."],
            ].map(([title, desc], i) => (
              <div key={i} style={{ display: "flex", gap: 12, paddingBottom: 16 }}>
                <div style={{ width: 20, height: 20, borderRadius: "50%", background: "#1e1e1e", border: "1px solid #333", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#555", flexShrink: 0, marginTop: 1 }}>{i + 1}</div>
                <div>
                  <div style={{ fontSize: 13, color: "#ededed", fontWeight: 500, marginBottom: 2 }}>{title}</div>
                  <div style={{ fontSize: 13, color: "#666" }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
          <CodeBlock lang="python" code={`# Resolve programmatically (e.g. from another agent or admin tool)
from agentshield import AgentShieldAdmin
from agentshield.models import HitlResolveRequest

admin = AgentShieldAdmin(bearer_token="your-auth0-token")
admin.resolve_hitl(
    request_id="req_...",
    request=HitlResolveRequest(decision="APPROVE", note="Verified invoice"),
)`} {...codeProps} />

          <div style={{ height: 60 }} />
        </div>
      </div>
    </div>
  );
}
