import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Home,
  Plus,
  Settings,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  bootstrapOnboarding,
  createAgent as createAgentRequest,
  getActivity,
  getDashboardStats,
  getNotifications,
  getOnboardingChecklist,
  listAgents,
  resolveRequest,
  submitSpendRequest,
} from "./lib/api";

const emptyChart = [
  { t: "00:00", safe: 0, blocked: 0, pending: 0 },
  { t: "04:00", safe: 0, blocked: 0, pending: 0 },
  { t: "08:00", safe: 0, blocked: 0, pending: 0 },
  { t: "12:00", safe: 0, blocked: 0, pending: 0 },
  { t: "16:00", safe: 0, blocked: 0, pending: 0 },
  { t: "20:00", safe: 0, blocked: 0, pending: 0 },
  { t: "24:00", safe: 0, blocked: 0, pending: 0 },
];

function normalizeStatus(status) {
  if (status === "PENDING_HITL") return "PENDING";
  if (status === "BLOCKED") return "BLOCKED";
  if (status === "APPROVED_BY_HUMAN_EXECUTED") return "APPROVED";
  if (status === "DENIED_BY_HUMAN") return "DENIED";
  return "SAFE";
}

function buildChecklistRows(payload, prefix) {
  return Object.entries(payload || {}).slice(0, 3).map(([k, v]) => {
    const ok = typeof v === "boolean" ? v : !String(v).toLowerCase().includes("exceed");
    return [`${prefix}${k}`, ok ? "✓" : "✗", String(typeof v === "object" ? JSON.stringify(v) : v)];
  });
}

const nav = [
  { key: "integration", label: "Integration", icon: ArrowUpRight },
  { key: "quickstart", label: "Quickstart", icon: Clock3 },
  { key: "overview", label: "Overview", icon: Home },
  { key: "activity", label: "Activity", icon: Activity },
  { key: "approvals", label: "Approvals", icon: AlertTriangle, pending: true },
  { key: "agents", label: "Agents", icon: Plus },
  { key: "settings", label: "Settings", icon: Settings },
];

const fx = {
  safe: { color: "var(--green)", bg: "rgba(0,200,83,0.12)" },
  pending: { color: "var(--amber)", bg: "rgba(255,149,0,0.14)" },
  blocked: { color: "var(--red)", bg: "rgba(255,59,48,0.14)" },
};

function badgeStyle(status) {
  if (status === "SAFE" || status === "APPROVED") return fx.safe;
  if (status === "PENDING") return fx.pending;
  return fx.blocked;
}

function statusLabel(status) {
  if (status === "BLOCKED") return "BLOCKED";
  if (status === "APPROVED") return "SAFE";
  if (status === "DENIED") return "BLOCKED";
  return status;
}

function Timer({ createdAt }) {
  const [s, setS] = useState(Math.floor((Date.now() - createdAt) / 1000));
  useEffect(() => {
    const i = setInterval(() => setS(Math.floor((Date.now() - createdAt) / 1000)), 1000);
    return () => clearInterval(i);
  }, [createdAt]);
  const mins = Math.floor(s / 60);
  const secs = String(s % 60).padStart(2, "0");
  const color = s >= 300 ? "var(--red)" : s >= 180 ? "var(--amber)" : "var(--text-2)";
  return <span style={{ color, fontFamily: "var(--font-mono)", fontSize: 12 }}>{mins}m {secs}s</span>;
}

function Toasts({ toasts }) {
  return (
    <div style={{ position: "fixed", right: 16, bottom: 16, zIndex: 50, display: "flex", flexDirection: "column", gap: 8 }}>
      {toasts.map((t) => (
        <div key={t.id} style={{ background: "var(--bg-overlay)", border: "1px solid var(--border-focus)", padding: "10px 12px", fontSize: 12 }}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [agents, setAgents] = useState([]);
  const [activeAgentId, setActiveAgentId] = useState("");
  const [stats, setStats] = useState({ total: 0, blocked: 0, pending: 0, approved: 0 });
  const [rows, setRows] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testRunning, setTestRunning] = useState(false);
  const [page, setPage] = useState("agents");
  const [filter, setFilter] = useState("All");
  const [expanded, setExpanded] = useState(null);
  const [rawOpen, setRawOpen] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [showSuccess, setShowSuccess] = useState(false);
  const [secretReveal, setSecretReveal] = useState(false);
  const [creds, setCreds] = useState({
    agentId: "agt_01j9xk2m4p8q3r7s",
    hmac: "sk_live_a8f3k9q7v1z2t4m6n8",
  });
  const [form, setForm] = useState({
    name: "",
    daily: "",
    perTx: "",
    auto: "",
    asset: "STABLECOIN",
    blocked: [],
    draftVendor: "",
    networks: ["base"],
    tokens: ["USDC"],
  });
  const [quickstartForm, setQuickstartForm] = useState({
    userName: "",
    email: "",
    agentName: "",
  });
  const [checklist, setChecklist] = useState(null);
  const [notes, setNotes] = useState({});

  const pendingCount = approvals.length;

  const filteredRows = useMemo(() => {
    if (filter === "All") return rows;
    if (filter === "Safe") return rows.filter((r) => ["SAFE", "APPROVED"].includes(r.status));
    if (filter === "Suspicious") return rows.filter((r) => ["PENDING", "APPROVED", "DENIED"].includes(r.status));
    return rows.filter((r) => ["BLOCKED", "DENIED"].includes(r.status));
  }, [rows, filter]);

  const toast = useCallback((msg) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, msg }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  const chartData = useMemo(() => {
    const hours = [0, 4, 8, 12, 16, 20, 24];
    const currentBucketIdx = Math.min(6, Math.floor(new Date().getHours() / 4));
    // Past/current buckets default to 0; future buckets are null so lines stop cleanly
    const buckets = hours.map((hour, idx) => ({
      t: `${String(hour).padStart(2, "0")}:00`,
      safe: idx <= currentBucketIdx ? 0 : null,
      blocked: idx <= currentBucketIdx ? 0 : null,
      pending: idx <= currentBucketIdx ? 0 : null,
    }));
    rows.forEach((row) => {
      const [h] = (row.time || "00:00:00").split(":");
      const idx = Math.min(6, Math.floor(Number(h) / 4));
      if (row.status === "SAFE" || row.status === "APPROVED") buckets[idx].safe += 1;
      else if (row.status === "BLOCKED" || row.status === "DENIED") buckets[idx].blocked += 1;
      else if (row.status === "PENDING") buckets[idx].pending += 1;
    });
    return buckets;
  }, [rows]);

  const refresh = useCallback(
    async (agentId) => {
      if (!agentId) return;
      const [statsResp, activityResp, notificationResp] = await Promise.all([
        getDashboardStats(agentId),
        getActivity(agentId),
        getNotifications(agentId),
      ]);
      setStats({
        total: statsResp.total_transactions_today,
        blocked: statsResp.blocked,
        pending: statsResp.pending_approval,
        approved: statsResp.auto_approved,
      });
      setRows(
        activityResp.activity.map((item) => {
          const slm = item.semantic_result || {};
          return {
            id: item.request_id,
            time: new Date(item.created_at).toLocaleTimeString("en-US", { hour12: false }),
            status: normalizeStatus(item.status),
            agent: agentId,
            vendor: item.vendor_url_or_name,
            amount: item.amount_cents / 100,
            asset: item.asset_type === "STABLECOIN" ? item.stablecoin_symbol || "USDC" : item.currency,
            network: item.network || "n/a",
            goal: item.declared_goal,
            reason: item.reason || item.verdict,
            details: {
              redis: buildChecklistRows(item.quantitative_result, ""),
              policy: buildChecklistRows(item.policy_result, ""),
              slm: {
                score: +(1 - Number(slm.risk_score ?? 50) / 100).toFixed(2),
                verdict: slm.alignment_label || item.verdict,
                reason: (slm.reason_codes || []).join(", ") || "No reason supplied",
              },
              raw: {
                request_id: item.request_id,
                declared_goal: item.declared_goal,
                amount_cents: item.amount_cents,
                currency: item.currency,
                vendor_url_or_name: item.vendor_url_or_name,
                network: item.network,
              },
            },
          };
        })
      );
      setApprovals(
        notificationResp.notifications.map((n) => {
          const payload = n.payload_json || {};
          const sem = payload.semantic_result || {};
          const score = +(1 - Number(sem.risk_score ?? 50) / 100).toFixed(2);
          return {
            id: n.id,
            requestId: n.request_id,
            createdAt: new Date(n.created_at).getTime(),
            goal: payload.declared_goal || "No goal provided",
            action: `Pay $${((payload.amount_cents || 0) / 100).toFixed(2)} ${payload.stablecoin_symbol || payload.currency || "USD"} → ${payload.vendor_url_or_name || "Unknown vendor"}`,
            meta: `${payload.item_description || "No item"} · ${payload.network || "n/a"} network · ${payload.destination_address || "n/a"}`,
            slmScore: score,
            slmVerdict: sem.alignment_label || payload.verdict || "SUSPICIOUS",
            slmReason: (sem.reason_codes || payload.reasons || []).join(", "),
            redis: buildChecklistRows(payload.quantitative_result, "").map((r) => `${r[1]} ${r[0]} ${r[2]}`),
            policy: buildChecklistRows(payload.policy_result, "").map((r) => `${r[1]} ${r[0]} ${r[2]}`),
          };
        })
      );
    },
    []
  );

  const refreshChecklist = useCallback(
    async (agentId) => {
      if (!agentId) return;
      try {
        const data = await getOnboardingChecklist(agentId);
        setChecklist(data);
      } catch {
        // checklist is best-effort for UX; ignore errors
      }
    },
    []
  );

  useEffect(() => {
    const init = async () => {
      try {
        const data = await listAgents();
        setAgents(data.agents);
        if (data.agents.length > 0) {
          const first = data.agents[0].agent_id;
          setActiveAgentId(first);
          setPage("integration");
          await refresh(first);
          await refreshChecklist(first);
        } else {
          setPage("quickstart");
        }
      } catch (err) {
        toast(err.message || "Unable to load agents");
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [refresh, toast]);

  useEffect(() => {
    if (!activeAgentId) return;
    const timer = setInterval(() => {
      refresh(activeAgentId).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [activeAgentId, refresh, refreshChecklist]);

  const resolve = (approvalId, decision) => {
    const ap = approvals.find((a) => String(a.id) === String(approvalId));
    if (!ap) return;
    resolveRequest(ap.requestId, decision)
      .then(() => refresh(activeAgentId))
      .then(() => refreshChecklist(activeAgentId))
      .then(() => {
        toast(decision === "APPROVE" ? "✓ Approved — agent resuming" : "✕ Denied — funds held");
      })
      .catch((err) => toast(err.message || "Resolve failed"));
  };

  const handleCreateAgent = (e) => {
    e.preventDefault();
    if (loading) return;
    if (!form.name || !form.daily || !form.perTx || !form.auto) return;
    createAgentRequest({
      agent_name: form.name,
      daily_spend_limit_usd: Number(form.daily),
      per_transaction_limit_usd: Number(form.perTx),
      auto_approve_under_usd: Number(form.auto),
      blocked_vendors: form.blocked.length ? form.blocked : ["unknown-vendor"],
      asset_type: form.asset,
      allowed_networks: form.networks,
      allowed_tokens: form.tokens,
    })
      .then(async (res) => {
        setShowSuccess(true);
        setCreds({ agentId: res.agent_id, hmac: res.hmac_secret });
        const data = await listAgents();
        setAgents(data.agents);
        setActiveAgentId(res.agent_id);
        await refresh(res.agent_id);
        await refreshChecklist(res.agent_id);
        setPage("integration");
      })
      .catch((err) => toast(err.message || "Create agent failed"));
  };

  const runQuickstartBootstrap = (e) => {
    e.preventDefault();
    if (!quickstartForm.userName || !quickstartForm.email || !quickstartForm.agentName) {
      toast("Enter name, email, and agent name");
      return;
    }
    bootstrapOnboarding({
      user_name: quickstartForm.userName,
      email: quickstartForm.email,
      agent_name: quickstartForm.agentName,
      daily_spend_limit_usd: 500,
      per_transaction_limit_usd: 100,
      auto_approve_under_usd: 25,
      allowed_networks: ["base"],
      allowed_tokens: ["USDC"],
      blocked_vendors: ["badvendor.example"],
    })
      .then(async (res) => {
        setShowSuccess(true);
        setCreds({ agentId: res.agent_id, hmac: res.hmac_secret });
        const data = await listAgents();
        setAgents(data.agents);
        setActiveAgentId(res.agent_id);
        await refresh(res.agent_id);
        await refreshChecklist(res.agent_id);
        setPage("integration");
        toast("Quickstart bootstrap complete");
      })
      .catch((err) => toast(err.message || "Bootstrap failed"));
  };

  const runSafeTest = () => {
    if (!activeAgentId || testRunning) return;
    setTestRunning(true);
    toast("Running SAFE test…");
    submitSpendRequest(activeAgentId, {
      agent_id: activeAgentId,
      declared_goal: "Book flight to NYC conference",
      amount_cents: 2400,
      currency: "USD",
      vendor_url_or_name: "Delta Airlines",
      item_description: "Seat reservation",
      asset_type: "STABLECOIN",
      stablecoin_symbol: "USDC",
      network: "base",
      destination_address: "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
      idempotency_key: `quick-safe-${Date.now()}`,
    })
      .then(() => Promise.all([refresh(activeAgentId), refreshChecklist(activeAgentId)]))
      .then(() => toast("✓ SAFE test complete"))
      .catch((err) => toast(err.message || "SAFE test failed"))
      .finally(() => setTestRunning(false));
  };

  const runSuspiciousTest = () => {
    if (!activeAgentId || testRunning) return;
    setTestRunning(true);
    toast("Running HITL test…");
    submitSpendRequest(activeAgentId, {
      agent_id: activeAgentId,
      declared_goal: "Book flight to NYC conference",
      amount_cents: 8900,
      currency: "USD",
      vendor_url_or_name: "Uber Eats",
      item_description: "Large dinner order",
      asset_type: "STABLECOIN",
      stablecoin_symbol: "USDC",
      network: "base",
      destination_address: "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
      idempotency_key: `quick-suspicious-${Date.now()}`,
    })
      .then(() => Promise.all([refresh(activeAgentId), refreshChecklist(activeAgentId)]))
      .then(() => {
        setPage("approvals");
        toast("✓ HITL test submitted — approve in Approvals");
      })
      .catch((err) => toast(err.message || "Suspicious test failed"))
      .finally(() => setTestRunning(false));
  };

  const addBlockedVendor = () => {
    const v = form.draftVendor.trim();
    if (!v) return;
    setForm((p) => ({ ...p, blocked: Array.from(new Set([...p.blocked, v])), draftVendor: "" }));
  };

  const effectiveAgentId = activeAgentId || creds.agentId || "agt_your_agent_id";
  const effectiveSecret = secretReveal ? creds.hmac : "<your-hmac-secret>";
  const apiBase = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/v1";
  const integrationPython = `import hashlib
import hmac
import json
from datetime import datetime, timezone

import requests

API_URL = "${apiBase}/spend-request"
AGENT_ID = "${effectiveAgentId}"
AGENT_HMAC_SECRET = "${effectiveSecret}"

body = {
    "agent_id": AGENT_ID,
    "declared_goal": "Book flight JFK Aug 1",
    "amount_cents": 4900,
    "currency": "USD",
    "vendor_url_or_name": "delta.com",
    "item_description": "Flight booking",
    "asset_type": "STABLECOIN",
    "stablecoin_symbol": "USDC",
    "network": "base",
    "destination_address": "0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    "idempotency_key": "agent-run-001",
}

timestamp = datetime.now(timezone.utc).isoformat()
body_json = json.dumps(body, separators=(",", ":"))
body_hash = hashlib.sha256(body_json.encode()).hexdigest()
canonical = "\\n".join(["POST", "/v1/spend-request", timestamp, body_hash, AGENT_ID])
signature = hmac.new(AGENT_HMAC_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()

response = requests.post(
    API_URL,
    headers={
        "Content-Type": "application/json",
        "x-agent-id": AGENT_ID,
        "x-timestamp": timestamp,
        "x-signature": signature,
    },
    data=body_json,
    timeout=15,
)

print(response.status_code, response.text)`;

  const pageTitle = page.charAt(0).toUpperCase() + page.slice(1);

  return (
    <div style={{ display: "flex", height: "100vh", width: "100vw", overflow: "hidden", background: "var(--bg)" }}>
      <style>{`
        :root {
          --bg: #0c0c0c;
          --bg-raised: #111111;
          --bg-overlay: #161616;
          --border: #222222;
          --border-focus: #333333;
          --text-1: #ededed;
          --text-2: #888888;
          --text-3: #444444;
          --amber: #FF9500;
          --green: #00C853;
          --red: #FF3B30;
          --blue: #0A84FF;
          --font-sans: "Geist", "IBM Plex Sans", sans-serif;
          --font-mono: "Geist Mono", "IBM Plex Mono", monospace;
        }
        * { box-sizing: border-box; }
        .cell { border-bottom: 1px solid var(--border); }
        .fast { transition: all 100ms ease; }
        .ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        button.fast:hover, .fast:hover {
          border-color: var(--border-focus) !important;
          background: var(--bg-overlay);
        }
        .dotPulse {
          width: 6px; height: 6px; border-radius: 999px; background: var(--amber);
          animation: dotPulse 1.1s infinite;
        }
        @keyframes dotPulse {
          0% { opacity: .35; transform: scale(.8); }
          50% { opacity: 1; transform: scale(1); }
          100% { opacity: .35; transform: scale(.8); }
        }
      `}</style>

      <aside style={{ width: 200, borderRight: "1px solid var(--border)", background: "var(--bg)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-1)", fontWeight: 500 }}>
          AgentShield
        </div>
        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", fontSize: 12, color: "var(--text-2)" }}>
          {agents.find((a) => a.agent_id === activeAgentId)?.display_name || "no-agent-selected"}
        </div>
        <nav style={{ paddingTop: 4, flex: 1 }}>
          {nav.map((n) => {
            const Icon = n.icon;
            const active = page === n.key;
            return (
              <button
                key={n.key}
                onClick={() => setPage(n.key)}
                style={{
                  width: "100%",
                  height: 34,
                  border: "none",
                  borderLeft: active ? "2px solid var(--text-1)" : "2px solid transparent",
                  background: active ? "var(--bg-raised)" : "transparent",
                  color: active ? "var(--text-1)" : "var(--text-2)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  paddingLeft: 16,
                  fontSize: 13,
                  cursor: "pointer",
                  fontFamily: "var(--font-sans)",
                }}
                className="fast"
              >
                <span style={{ display: "inline-flex", width: 14, alignItems: "center", justifyContent: "center" }}>
                  <Icon size={13} />
                </span>
                <span style={{ lineHeight: "14px" }}>{n.label}</span>
                {n.pending && pendingCount > 0 ? (
                  <span style={{ marginLeft: "auto", marginRight: 12, width: 6, height: 6, borderRadius: 999, background: "var(--amber)" }} />
                ) : null}
              </button>
            );
          })}
        </nav>
        <div style={{ padding: "10px 16px", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--green)", fontFamily: "var(--font-mono)" }}>
          ● API Operational
        </div>
      </aside>

      <main style={{ flex: 1, overflowY: "auto", background: "var(--bg)" }}>
        <header style={{ height: 48, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-1)" }}>{pageTitle}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {activeAgentId ? (
              <select
                value={activeAgentId}
                onChange={(e) => {
                  setActiveAgentId(e.target.value);
                  refresh(e.target.value).catch(() => {});
                  refreshChecklist(e.target.value).catch(() => {});
                }}
                style={{ background: "var(--bg-raised)", border: "1px solid var(--border)", color: "var(--text-2)", height: 28, fontSize: 12, padding: "0 8px", fontFamily: "var(--font-mono)" }}
              >
                {agents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.display_name}
                  </option>
                ))}
              </select>
            ) : null}
            <div style={{ fontSize: 12, color: "var(--text-2)" }}>{page === "activity" ? "↑ Export" : ""}</div>
          </div>
        </header>

        <section style={{ padding: 24 }}>
          {page === "integration" ? (
            <div style={{ maxWidth: 900 }}>
              <div style={{ border: "1px solid var(--border)", padding: 12, marginBottom: 12 }}>
                <div style={{ fontSize: 13, color: "var(--text-1)", fontFamily: "var(--font-mono)", marginBottom: 8 }}>
                  Agent Integration (Primary)
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 8 }}>
                  Agents should call `POST /v1/spend-request` directly from their workflow. This is the production path.
                </div>
                <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
                  endpoint: {apiBase}/spend-request
                </div>
                <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
                  agent_id: {effectiveAgentId}
                </div>
              </div>

              <div style={{ border: "1px solid var(--border)", padding: 12, marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 8 }}>Signing Rules</div>
                <div style={{ fontSize: 11, color: "var(--text-1)", fontFamily: "var(--font-mono)", marginBottom: 8 }}>
                  canonical = METHOD + "\n" + PATH + "\n" + x-timestamp + "\n" + sha256(body) + "\n" + x-agent-id
                </div>
                <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                  Send `x-agent-id`, `x-timestamp`, and `x-signature` (HMAC-SHA256). In local dev, you can still use `x-agent-key: local-dev-key`.
                </div>
              </div>

              <div style={{ border: "1px solid var(--border)", background: "var(--bg-raised)", padding: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: "var(--text-2)" }}>Generated Python Snippet</div>
                  <button
                    onClick={() => navigator.clipboard.writeText(integrationPython)}
                    disabled={!secretReveal}
                    title={!secretReveal ? "Reveal your HMAC secret first" : "Copy snippet"}
                    style={{ border: "none", background: "transparent", color: secretReveal ? "var(--text-2)" : "var(--text-3)", fontSize: 11, cursor: secretReveal ? "pointer" : "not-allowed" }}
                  >
                    {secretReveal ? "[copy]" : "[reveal secret to copy]"}
                  </button>
                </div>
                <pre style={{ margin: 0, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-1)", whiteSpace: "pre-wrap" }}>
                  {integrationPython}
                </pre>
              </div>
            </div>
          ) : null}

          {page === "quickstart" ? (
            <div style={{ maxWidth: 780 }}>
              <div style={{ border: "1px solid var(--border)", padding: 12, marginBottom: 12 }}>
                <div style={{ fontSize: 13, color: "var(--text-1)", fontFamily: "var(--font-mono)", marginBottom: 8 }}>
                  5-Minute Onboarding
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>
                  Create your first agent, run one SAFE and one HITL test, then approve once.
                </div>
                <form onSubmit={runQuickstartBootstrap} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8 }}>
                  <input
                    value={quickstartForm.userName}
                    onChange={(e) => setQuickstartForm((p) => ({ ...p, userName: e.target.value }))}
                    placeholder="your name"
                    style={{ height: 32, border: "1px solid var(--border)", background: "var(--bg-raised)", color: "var(--text-1)", padding: "0 8px", fontSize: 12, fontFamily: "var(--font-mono)" }}
                  />
                  <input
                    value={quickstartForm.email}
                    onChange={(e) => setQuickstartForm((p) => ({ ...p, email: e.target.value }))}
                    placeholder="email"
                    style={{ height: 32, border: "1px solid var(--border)", background: "var(--bg-raised)", color: "var(--text-1)", padding: "0 8px", fontSize: 12, fontFamily: "var(--font-mono)" }}
                  />
                  <input
                    value={quickstartForm.agentName}
                    onChange={(e) => setQuickstartForm((p) => ({ ...p, agentName: e.target.value }))}
                    placeholder="agent name"
                    style={{ height: 32, border: "1px solid var(--border)", background: "var(--bg-raised)", color: "var(--text-1)", padding: "0 8px", fontSize: 12, fontFamily: "var(--font-mono)" }}
                  />
                  <button
                    type="submit"
                    style={{ height: 32, border: "1px solid var(--text-1)", background: "var(--text-1)", color: "var(--bg)", padding: "0 10px", fontFamily: "var(--font-mono)", fontSize: 12, cursor: "pointer" }}
                  >
                    Bootstrap
                  </button>
                </form>
              </div>

              {activeAgentId ? (
                <div style={{ border: "1px solid var(--border)", padding: 12, marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 2 }}>Developer Tools</div>
                  <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 10 }}>
                    These actions simulate external agent calls for onboarding and testing.
                  </div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                    <button
                      onClick={runSafeTest}
                      disabled={testRunning}
                      style={{ height: 30, border: `1px solid ${testRunning ? "var(--border)" : "var(--green)"}`, background: testRunning ? "transparent" : "rgba(0,200,83,0.12)", color: testRunning ? "var(--text-3)" : "var(--green)", padding: "0 10px", fontFamily: "var(--font-mono)", fontSize: 11, cursor: testRunning ? "not-allowed" : "pointer" }}
                    >
                      {testRunning ? "running…" : "Run SAFE Test"}
                    </button>
                    <button
                      onClick={runSuspiciousTest}
                      disabled={testRunning}
                      style={{ height: 30, border: `1px solid ${testRunning ? "var(--border)" : "var(--amber)"}`, background: testRunning ? "transparent" : "rgba(255,149,0,0.12)", color: testRunning ? "var(--text-3)" : "var(--amber)", padding: "0 10px", fontFamily: "var(--font-mono)", fontSize: 11, cursor: testRunning ? "not-allowed" : "pointer" }}
                    >
                      {testRunning ? "running…" : "Run HITL Test"}
                    </button>
                    <button
                      onClick={() => refreshChecklist(activeAgentId)}
                      disabled={testRunning}
                      style={{ height: 30, border: "1px solid var(--border)", background: "var(--bg-raised)", color: testRunning ? "var(--text-3)" : "var(--text-2)", padding: "0 10px", fontFamily: "var(--font-mono)", fontSize: 11, cursor: testRunning ? "not-allowed" : "pointer" }}
                    >
                      Refresh Checklist
                    </button>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
                    active_agent: {activeAgentId}
                  </div>
                </div>
              ) : null}

              <div style={{ border: "1px solid var(--border)", padding: 12 }}>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 8 }}>Readiness</div>
                {checklist ? (
                  <>
                    {[
                      ["Agent created", checklist.agent_created],
                      ["First transaction submitted", checklist.first_transaction_submitted],
                      ["First human decision made", checklist.human_decision_made],
                    ].map(([label, ok]) => (
                      <div key={label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                        <span style={{ fontSize: 12, color: "var(--text-1)" }}>{label}</span>
                        <span style={{ fontSize: 11, color: ok ? "var(--green)" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
                          {ok ? "DONE" : "PENDING"}
                        </span>
                      </div>
                    ))}
                    <div style={{ marginTop: 10, fontSize: 12, color: checklist.ready_for_live ? "var(--green)" : "var(--text-2)", fontFamily: "var(--font-mono)" }}>
                      {checklist.ready_for_live ? "READY FOR LIVE AGENT TRAFFIC" : "Complete the checklist to go live"}
                    </div>
                  </>
                ) : (
                  <div style={{ fontSize: 12, color: "var(--text-3)" }}>No checklist yet. Bootstrap an agent first.</div>
                )}
              </div>
            </div>
          ) : null}

          {page === "overview" ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
                {[
                  ["transactions", stats.total, "today", "var(--text-1)"],
                  ["blocked", stats.blocked, "", "var(--red)"],
                  ["pending", stats.pending, "", "var(--amber)"],
                  ["approved", stats.approved, "", "var(--green)"],
                ].map(([label, value, sub, color]) => (
                  <div key={label} style={{ border: "1px solid var(--border)", padding: 10 }}>
                    <div style={{ fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
                    <div style={{ marginTop: 8, fontSize: 26, lineHeight: 1, color, fontFamily: "var(--font-mono)", fontWeight: 600 }}>{value}</div>
                    <div style={{ marginTop: 3, fontSize: 11, color: "var(--text-3)" }}>{sub}</div>
                  </div>
                ))}
              </div>

              <div style={{ marginTop: 16, border: "1px solid var(--border)", padding: 12 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: "var(--text-2)" }}>Request Activity</div>
                  <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--text-3)" }}>
                    <span style={{ color: "var(--green)" }}>— safe</span>
                    <span style={{ color: "var(--red)" }}>— blocked</span>
                    <span style={{ color: "var(--amber)" }}>— pending</span>
                  </div>
                </div>
                <div style={{ height: 220 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <XAxis dataKey="t" tick={{ fill: "var(--text-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis allowDecimals={false} tick={{ fill: "var(--text-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)" }} />
                      <ReferenceLine y={0} stroke="var(--border)" strokeWidth={1} />
                      <Line dataKey="safe" stroke="var(--green)" strokeWidth={1.5} dot={false} />
                      <Line dataKey="blocked" stroke="var(--red)" strokeWidth={1.5} dot={false} />
                      <Line dataKey="pending" stroke="var(--amber)" strokeWidth={1.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div style={{ marginTop: 16, border: "1px solid var(--border)" }}>
                <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)", fontSize: 12, color: "var(--text-2)" }}>Recent Activity</div>
                {rows.slice(0, 5).map((r) => (
                  <div key={r.id} className="cell" style={{ display: "grid", gridTemplateColumns: "100px 160px 1fr 100px 80px", alignItems: "center", height: 36, padding: "0 12px", fontSize: 12, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-2)" }}>{r.time}</div>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.vendor}</div>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-2)", fontStyle: "italic" }}>{r.goal}</div>
                    <div style={{ fontFamily: "var(--font-mono)", textAlign: "right" }}>${r.amount.toFixed(2)}</div>
                    <div style={{ color: "var(--text-3)", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.network}</div>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          {page === "activity" ? (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <div style={{ display: "flex", gap: 14, fontSize: 12 }}>
                  {["All", "Safe", "Suspicious", "Blocked"].map((f) => (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      style={{
                        border: "none",
                        borderBottom: filter === f ? "1px solid var(--text-1)" : "1px solid transparent",
                        background: "transparent",
                        color: filter === f ? "var(--text-1)" : "var(--text-2)",
                        paddingBottom: 5,
                        lineHeight: "14px",
                        cursor: "pointer",
                        fontSize: 12,
                      }}
                    >
                      {f}
                    </button>
                  ))}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>↑ Export</div>
              </div>
              <div style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "82px 92px 112px 1fr 116px 78px 1fr 20px", padding: "6px 12px", fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
                  <div>Time</div><div>Status</div><div>Agent</div><div>Vendor</div><div style={{ textAlign: "right" }}>Amount</div><div>Network</div><div>Goal</div><div />
                </div>
                {filteredRows.map((r) => {
                  const b = badgeStyle(r.status);
                  const open = expanded === r.id;
                  return (
                    <div key={r.id} style={{ borderTop: "1px solid var(--border)" }}>
                      <div
                        onClick={() => setExpanded((p) => (p === r.id ? null : r.id))}
                        style={{ display: "grid", gridTemplateColumns: "82px 92px 112px 1fr 116px 78px 1fr 20px", alignItems: "center", minHeight: 36, padding: "0 12px", fontSize: 12, cursor: "pointer", background: open ? "var(--bg-raised)" : "transparent" }}
                        className="fast"
                      >
                        <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-2)" }}>{r.time}</div>
                        <div>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "2px 6px", fontSize: 10, borderRadius: 3, color: b.color, background: b.bg, textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
                            {r.status === "PENDING" ? <span className="dotPulse" /> : null}
                            {statusLabel(r.status)}
                          </span>
                        </div>
                        <div className="ellipsis" style={{ color: "var(--text-2)" }}>{r.agent}</div>
                        <div className="ellipsis" style={{ color: "var(--text-1)", fontSize: 13 }}>{r.vendor}</div>
                        <div style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                          ${r.amount.toFixed(2)} <span style={{ color: "var(--text-3)", fontSize: 11 }}>{r.asset}</span>
                        </div>
                        <div style={{ color: "var(--text-3)", fontSize: 11 }}>{r.network}</div>
                        <div className="ellipsis" style={{ color: "var(--text-2)", fontStyle: "italic" }}>{r.goal}</div>
                        <div style={{ color: open ? "var(--text-1)" : "var(--text-3)" }}>→</div>
                      </div>

                      {open ? (
                        <div style={{ background: "var(--bg-raised)", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", padding: 10, display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 10 }}>
                          <div style={{ fontSize: 12 }}>
                            <div style={{ color: "var(--text-2)", fontSize: 11, marginBottom: 6 }}>Check A · Redis</div>
                            {r.details.redis.map(([k, s, v]) => <div key={k} style={{ display: "grid", gridTemplateColumns: "140px 20px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>{k}</span><span>{s}</span><span>{v}</span></div>)}
                            <div style={{ color: "var(--text-2)", fontSize: 11, margin: "6px 0 6px" }}>Check B · Policy</div>
                            {r.details.policy.map(([k, s, v]) => <div key={k} style={{ display: "grid", gridTemplateColumns: "140px 20px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>{k}</span><span>{s}</span><span>{v}</span></div>)}
                            <div style={{ color: "var(--text-2)", fontSize: 11, margin: "6px 0 6px" }}>Check C · SLM</div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>alignment score</span><span>{r.details.slm.score}</span></div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>verdict</span><span>{r.details.slm.verdict}</span></div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr" }}><span style={{ color: "var(--text-2)" }}>reason</span><span>{r.details.slm.reason}</span></div>
                          </div>
                          <div>
                            <button onClick={() => setRawOpen((p) => (p === r.id ? null : r.id))} style={{ background: "transparent", border: "none", color: "var(--text-2)", fontSize: 11, cursor: "pointer", padding: 0 }}>
                              {"{ } Raw Request"}
                            </button>
                            {rawOpen === r.id ? (
                              <pre style={{ marginTop: 8, background: "var(--bg-overlay)", border: "1px solid var(--border)", padding: 8, fontFamily: "var(--font-mono)", fontSize: 11, overflow: "auto" }}>
                                {JSON.stringify(r.details.raw, null, 2)}
                              </pre>
                            ) : null}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}

          {page === "approvals" ? (
            approvals.length === 0 ? (
              <div style={{ display: "grid", placeItems: "center", minHeight: 460, textAlign: "center" }}>
                <ShieldCheck size={32} color="var(--text-3)" />
                <div style={{ marginTop: 8, fontSize: 14, color: "var(--text-1)" }}>No pending approvals</div>
                <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-2)" }}>All agent activity is within policy</div>
              </div>
            ) : (
              <>
                <div style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ fontSize: 13, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>Approvals</div>
                  <span style={{ fontSize: 11, color: "var(--amber)", border: "1px solid var(--border)", background: "rgba(255,149,0,0.14)", padding: "2px 6px" }}>{approvals.length} pending</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>
                  Transactions paused for human review. Agent is waiting.
                </div>
                <div style={{ display: "grid", gap: 8 }}>
                  {approvals.map((a) => {
                    const barColor = a.slmScore < 0.4 ? "var(--red)" : a.slmScore < 0.7 ? "var(--amber)" : "var(--green)";
                    return (
                      <div key={a.id} style={{ border: "1px solid var(--border)", background: "var(--bg-raised)" }} className="fast">
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid var(--border)", background: "var(--bg-overlay)", fontSize: 12 }}>
                          <span style={{ color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>PENDING APPROVAL</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <Timer createdAt={a.createdAt} />
                            <ShieldAlert size={14} color="var(--amber)" />
                          </span>
                        </div>
                        <div style={{ padding: 10, fontSize: 12 }}>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>Goal</span><span>{a.goal}</span>
                          </div>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>Action</span>
                            <div>
                              <div>{a.action}</div>
                              <div style={{ marginTop: 3, color: "var(--text-2)", fontSize: 11, fontFamily: "var(--font-mono)" }}>{a.meta}</div>
                            </div>
                          </div>
                        </div>
                        <div style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", padding: 10, fontSize: 12 }}>
                          <div style={{ color: "var(--text-2)", marginBottom: 8 }}>SIGNALS</div>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>SLM Score</span>
                            <div>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                                <span>{a.slmScore.toFixed(2)}</span><span>{a.slmVerdict}</span>
                              </div>
                              <div style={{ height: 2, background: "var(--border)", marginBottom: 6 }}>
                                <div style={{ width: `${a.slmScore * 100}%`, height: "100%", background: barColor }} />
                              </div>
                              <div style={{ color: "var(--text-2)" }}>{a.slmReason}</div>
                            </div>
                          </div>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>Redis</span>
                            <div>{a.redis.map((s) => <div key={s}>{s}</div>)}</div>
                          </div>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr" }}>
                            <span style={{ color: "var(--text-2)" }}>Policy</span>
                            <div>{a.policy.map((s) => <div key={s}>{s}</div>)}</div>
                          </div>
                        </div>
                        <div style={{ padding: 10 }}>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>Note</span>
                            <input
                              value={notes[a.id] || ""}
                              onChange={(e) => setNotes((p) => ({ ...p, [a.id]: e.target.value }))}
                              style={{ height: 28, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text-1)", padding: "0 8px", fontSize: 12 }}
                            />
                          </div>
                          <div style={{ display: "flex", justifyContent: "space-between" }}>
                            <button
                              onClick={() => resolve(a.id, "APPROVE")}
                              style={{ height: 30, padding: "0 12px", border: "1px solid var(--green)", background: "var(--green)", color: "var(--bg)", fontFamily: "var(--font-mono)", fontSize: 12, cursor: "pointer" }}
                              className="fast"
                            >
                              ✓ Approve
                            </button>
                            <button
                              onClick={() => resolve(a.id, "DENY")}
                              style={{ height: 30, padding: "0 12px", border: "1px solid transparent", background: "transparent", color: "var(--red)", fontFamily: "var(--font-mono)", fontSize: 12, cursor: "pointer" }}
                              className="fast"
                            >
                              ✕ Deny
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )
          ) : null}

          {page === "agents" ? (
            <div style={{ maxWidth: 560 }}>
              <div style={{ marginBottom: 12, fontSize: 13, color: "var(--text-1)", fontFamily: "var(--font-mono)" }}>Register Agent</div>
              {!showSuccess ? (
                <form onSubmit={handleCreateAgent}>
                  {[
                    ["Agent Name", "name", "my-booking-agent", false, null],
                    ["Daily Spend Limit", "daily", "500", true, "Max total USD the agent can spend per day"],
                    ["Per-Transaction Limit", "perTx", "200", true, "Max USD allowed per single transaction"],
                    ["Auto-Approve Under", "auto", "25", true, "Transactions below this USD amount skip HITL review"],
                  ].map(([label, key, ph, numeric, hint]) => (
                    <div key={key} style={{ marginBottom: 12 }}>
                      <label style={{ display: "block", marginBottom: 4, fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                        {label}{numeric ? <span style={{ color: "var(--text-3)", textTransform: "none", marginLeft: 6 }}>USD</span> : null}
                      </label>
                      {hint ? <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 4 }}>{hint}</div> : null}
                      <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                        {numeric ? <span style={{ position: "absolute", left: 10, fontSize: 13, color: "var(--text-2)", fontFamily: "var(--font-mono)", pointerEvents: "none" }}>$</span> : null}
                        <input
                          type={numeric ? "number" : "text"}
                          min={numeric ? 1 : undefined}
                          step={numeric ? 1 : undefined}
                          value={form[key]}
                          placeholder={ph}
                          onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                          style={{ width: "100%", height: 36, background: "var(--bg-raised)", border: "1px solid var(--border)", color: "var(--text-1)", borderRadius: 4, paddingLeft: numeric ? 22 : 12, paddingRight: 12, fontSize: 13, fontFamily: "var(--font-mono)" }}
                          className="fast"
                        />
                      </div>
                    </div>
                  ))}
                  <div style={{ marginBottom: 12 }}>
                    <label style={{ display: "block", marginBottom: 4, fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Asset Type</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {["STABLECOIN", "FIAT"].map((asset) => (
                        <button key={asset} type="button" onClick={() => setForm((p) => ({ ...p, asset }))} style={{ height: 30, padding: "0 10px", border: "1px solid var(--border)", background: form.asset === asset ? "var(--bg-overlay)" : "var(--bg-raised)", color: "var(--text-1)", borderRadius: 4, fontSize: 12, fontFamily: "var(--font-mono)" }}>
                          {asset}
                        </button>
                      ))}
                    </div>
                  </div>
                  {form.asset === "STABLECOIN" ? (
                    <>
                      <div style={{ marginBottom: 12 }}>
                        <label style={{ display: "block", marginBottom: 4, fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Networks</label>
                        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12, color: "var(--text-2)" }}>
                          {["ethereum", "base", "solana", "polygon", "arbitrum"].map((n) => (
                            <label key={n} style={{ display: "inline-flex", gap: 6, alignItems: "center", textTransform: "lowercase" }}>
                              <input type="checkbox" checked={form.networks.includes(n)} onChange={() => setForm((p) => ({ ...p, networks: p.networks.includes(n) ? p.networks.filter((x) => x !== n) : [...p.networks, n] }))} />
                              {n}
                            </label>
                          ))}
                        </div>
                      </div>
                      <div style={{ marginBottom: 12 }}>
                        <label style={{ display: "block", marginBottom: 4, fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Tokens</label>
                        <div style={{ display: "flex", gap: 8 }}>
                          {["USDC", "USDT"].map((t) => (
                            <button key={t} type="button" onClick={() => setForm((p) => ({ ...p, tokens: p.tokens.includes(t) ? p.tokens.filter((x) => x !== t) : [...p.tokens, t] }))} style={{ height: 28, padding: "0 10px", border: "1px solid var(--border)", background: form.tokens.includes(t) ? "var(--bg-overlay)" : "var(--bg-raised)", color: "var(--text-1)", borderRadius: 4, fontFamily: "var(--font-mono)", fontSize: 11 }}>
                              {t}
                            </button>
                          ))}
                        </div>
                      </div>
                    </>
                  ) : null}
                  <div style={{ marginBottom: 12 }}>
                    <label style={{ display: "block", marginBottom: 4, fontSize: 11, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Blocked Vendors</label>
                    <input
                      value={form.draftVendor}
                      onChange={(e) => setForm((p) => ({ ...p, draftVendor: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addBlockedVendor(); } }}
                      style={{ width: "100%", height: 36, background: "var(--bg-raised)", border: "1px solid var(--border)", color: "var(--text-1)", borderRadius: 4, padding: "0 12px", fontSize: 13, fontFamily: "var(--font-mono)" }}
                      className="fast"
                    />
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                      {form.blocked.map((v) => (
                        <button key={v} type="button" onClick={() => setForm((p) => ({ ...p, blocked: p.blocked.filter((x) => x !== v) }))} style={{ border: "1px solid var(--border)", background: "var(--bg-raised)", color: "var(--text-2)", borderRadius: 4, fontSize: 11, fontFamily: "var(--font-mono)", padding: "3px 6px" }}>
                          {v} ×
                        </button>
                      ))}
                    </div>
                  </div>
                  <button type="submit" style={{ height: 36, padding: "0 16px", border: "1px solid var(--text-1)", background: "var(--text-1)", color: "var(--bg)", borderRadius: 4, fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
                    Create Agent
                  </button>
                </form>
              ) : (
                <div>
                  <div style={{ fontSize: 14, color: "var(--text-1)", fontFamily: "var(--font-mono)", fontWeight: 500, marginBottom: 10 }}>Agent created.</div>
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>agent_id</div>
                    <div style={{ border: "1px solid var(--border)", background: "var(--bg-raised)", padding: "8px 10px", display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                      <span>{creds.agentId}</span>
                      <button onClick={() => navigator.clipboard.writeText(creds.agentId)} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>[copy]</button>
                    </div>
                  </div>
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>hmac_secret</div>
                    <div style={{ border: "1px solid var(--border)", background: "var(--bg-raised)", padding: "8px 10px", display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                      <span>{secretReveal ? creds.hmac : "•••••••••••••••••••••••••••"}</span>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button onClick={() => navigator.clipboard.writeText(creds.hmac)} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>[copy]</button>
                        <button onClick={() => setSecretReveal((p) => !p)} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>[reveal]</button>
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>Integration</div>
                  <div style={{ border: "1px solid var(--border)", background: "var(--bg-overlay)", padding: "8px 10px", fontFamily: "var(--font-mono)", fontSize: 12, position: "relative" }}>
                    <button onClick={() => navigator.clipboard.writeText(`curl -X POST https://api.agentshield.com/v1/spend-request -H "x-agent-id: ${creds.agentId}" -H "x-signature: <hmac>" -d '{"declared_goal":"...","amount_cents":4900}'`)} style={{ position: "absolute", right: 8, top: 8, border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>[copy]</button>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{`curl -X POST \\
  https://api.agentshield.com/v1/spend-request \\
  -H "x-agent-id: ${creds.agentId}" \\
  -H "x-signature: <hmac>" \\
  -d '{"declared_goal":"...","amount_cents":4900}'`}</pre>
                  </div>
                  <button onClick={() => setPage("activity")} style={{ marginTop: 10, border: "none", background: "transparent", color: "var(--text-2)", fontSize: 12, cursor: "pointer" }}>
                    → View Activity
                  </button>
                </div>
              )}
            </div>
          ) : null}

          {page === "settings" ? (
            <div style={{ border: "1px solid var(--border)", padding: 12, fontSize: 12, color: "var(--text-2)" }}>
              Settings coming soon.
            </div>
          ) : null}
        </section>
      </main>
      <Toasts toasts={toasts} />
    </div>
  );
}

