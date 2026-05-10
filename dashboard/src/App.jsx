import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AgentsPanel from "./components/AgentsPanel";
import DocsPage from "./DocsPage";
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
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  createAgent as createAgentRequest,
  getActivity,
  getDashboardStats,
  getNotifications,
  getOnboardingChecklist,
  listAgents,
  resolveRequest,
  runDevTestRequest,
  updateAgentSettings,
  updateAgentScopes,
} from "./lib/api";
import { logout } from "./lib/auth";

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
  { key: "agents", label: "Agents", icon: Plus },
  { key: "overview", label: "Overview", icon: Home },
  { key: "activity", label: "Activity", icon: Activity },
  { key: "approvals", label: "Approvals", icon: AlertTriangle, pending: true },
  { key: "docs", label: "Docs", icon: ArrowUpRight },
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
  const [activityMeta, setActivityMeta] = useState({ totalToday: 0, countMode: "today_utc" });
  const [rows, setRows] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [safeRunning, setSafeRunning] = useState(false);
  const [hitlRunning, setHitlRunning] = useState(false);
  const [checklistRefreshing, setChecklistRefreshing] = useState(false);
  const [page, setPage] = useState("agents");
  const [filter, setFilter] = useState("All");
  const [expanded, setExpanded] = useState(null);
  const [rawOpen, setRawOpen] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [showSuccess, setShowSuccess] = useState(false);
  const [secretReveal, setSecretReveal] = useState(false);
  const [showNewAgentForm, setShowNewAgentForm] = useState(false);
  const [credsMap, setCredsMap] = useState(() => {
    try { return JSON.parse(localStorage.getItem("agentshield_creds_map")) || {}; }
    catch { return {}; }
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
    scopes: [],
    draftScope: "",
  });
  const [checklist, setChecklist] = useState(null);
  const [notes, setNotes] = useState({});
  const [scopesSaving, setScopesSaving] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const activeAgentRef = useRef("");

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
    const buckets = hours.map((hour) => ({
      t: `${String(hour).padStart(2, "0")}:00`,
      safe: 0,
      blocked: 0,
      pending: 0,
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
    async (agentId, silent = false) => {
      if (!agentId) return;
      const [statsResp, activityResp, notificationResp] = await Promise.all([
        getDashboardStats(agentId),
        getActivity(agentId),
        getNotifications(agentId),
      ]);
      if (agentId !== activeAgentRef.current) {
        return;
      }
      setStats({
        total: activityResp.total_transactions_today ?? statsResp.total_transactions_today,
        blocked: statsResp.blocked,
        pending: statsResp.pending_approval,
        approved: statsResp.auto_approved,
      });
      setActivityMeta({
        totalToday: activityResp.total_transactions_today ?? 0,
        countMode: activityResp.count_mode || "today_utc",
      });
      const newRows = activityResp.activity.map((item) => {
        const slm = item.semantic_result || {};
        const gd = item.goal_drift_result || {};
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
            goalDrift: {
              skipped: gd.skipped ?? true,
              within_scope: gd.within_scope ?? true,
              matched_scope: gd.matched_scope ?? null,
              reason: gd.reason ?? "",
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
      });
      setRows(() => newRows);
      setApprovals(
        notificationResp.notifications.map((n) => {
          const payload = n.payload_json || {};
          const sem = payload.semantic_result || {};
          const gd = payload.goal_drift_result || {};
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
            goalDrift: {
              skipped: gd.skipped ?? true,
              within_scope: gd.within_scope ?? true,
              matched_scope: gd.matched_scope ?? null,
              reason: gd.reason ?? "",
            },
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
          const storedMap = (() => { try { return JSON.parse(localStorage.getItem("agentshield_creds_map") || "{}"); } catch { return {}; } })();
          const match = Object.keys(storedMap).find((id) => data.agents.find((a) => a.agent_id === id));
          const first = match || data.agents[0].agent_id;
          activeAgentRef.current = first;
          setActiveAgentId(first);
          setPage("agents");
          await refresh(first, true);
          await refreshChecklist(first);
        } else {
          setPage("agents");
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
    activeAgentRef.current = activeAgentId;
    const timer = setInterval(() => {
      refresh(activeAgentId).catch(() => {});
    }, 2000);
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
    if (!form.name || form.daily === "" || form.perTx === "" || form.auto === "") return;
    const dailyUsd = Math.trunc(Number(form.daily));
    const perTxnUsd = Math.trunc(Number(form.perTx));
    const autoApproveUsd = Math.trunc(Number(form.auto));
    if (
      !Number.isFinite(dailyUsd) ||
      !Number.isFinite(perTxnUsd) ||
      !Number.isFinite(autoApproveUsd) ||
      dailyUsd < 0 ||
      perTxnUsd < 0 ||
      autoApproveUsd < 0
    ) {
      toast("Spend limits must be non-negative numbers.");
      return;
    }
    createAgentRequest({
      agent_name: form.name,
      daily_spend_limit_usd: dailyUsd,
      per_transaction_limit_usd: perTxnUsd,
      auto_approve_under_usd: autoApproveUsd,
      blocked_vendors: form.blocked,
      asset_type: form.asset,
      allowed_networks: form.networks,
      allowed_tokens: form.tokens,
      allowed_scopes: form.scopes,
    })
      .then(async (res) => {
        setCredsMap((prev) => {
          const next = { ...prev, [res.agent_id]: res.hmac_secret };
          localStorage.setItem("agentshield_creds_map", JSON.stringify(next));
          return next;
        });
        setShowSuccess(true);
        const data = await listAgents();
        setAgents(data.agents);
        activeAgentRef.current = res.agent_id;
        setActiveAgentId(res.agent_id);
        setShowNewAgentForm(false);
        setForm({
          name: "",
          daily: "",
          perTx: "",
          auto: "",
          asset: "STABLECOIN",
          blocked: [],
          draftVendor: "",
          networks: ["base"],
          tokens: ["USDC"],
          scopes: [],
          draftScope: "",
        });
        await refresh(res.agent_id, true);
        await refreshChecklist(res.agent_id);
      })
      .catch((err) => toast(err.message || "Create agent failed"));
  };

  const runSafeTest = () => {
    if (!activeAgentId || safeRunning) return;
    setSafeRunning(true);
    toast("Running SAFE test…");
    const safeAddr = "0x" + crypto.getRandomValues(new Uint8Array(20)).reduce((s, b) => s + b.toString(16).padStart(2, "0"), "");
    runDevTestRequest(activeAgentId, {
      agent_id: activeAgentId,
      declared_goal: "Pay contractor invoice for logo design work",
      amount_cents: 100,
      currency: "USD",
      vendor_url_or_name: "contractor.eth",
      item_description: "Logo design invoice #12",
      asset_type: "STABLECOIN",
      stablecoin_symbol: "USDC",
      network: "base",
      destination_address: safeAddr,
      idempotency_key: `quick-safe-${Date.now()}`,
    })
      .then((result) => {
        if (result?.idempotency_replay) {
          toast("⚠ Replay detected: cached AgentShield decision returned (no new evaluation).");
        }
        return result;
      })
      .then(() => Promise.all([refresh(activeAgentId, true), refreshChecklist(activeAgentId)]))
      .then(() => toast("✓ SAFE test complete"))
      .catch((err) => toast(err.message || "SAFE test failed"))
      .finally(() => setSafeRunning(false));
  };

  const runSuspiciousTest = () => {
    if (!activeAgentId || hitlRunning) return;
    setHitlRunning(true);
    toast("Running HITL test…");
    const hitlAddr = "0x" + crypto.getRandomValues(new Uint8Array(20)).reduce((s, b) => s + b.toString(16).padStart(2, "0"), "");
    runDevTestRequest(activeAgentId, {
      agent_id: activeAgentId,
      declared_goal: "Subscribe to GitHub Enterprise for the engineering team",
      amount_cents: 50000,
      currency: "USD",
      vendor_url_or_name: "github.com",
      item_description: "GitHub Enterprise Cloud annual subscription",
      asset_type: "STABLECOIN",
      stablecoin_symbol: "USDC",
      network: "base",
      destination_address: hitlAddr,
      idempotency_key: `quick-suspicious-${Date.now()}`,
    })
      .then((result) => {
        if (result?.idempotency_replay) {
          toast("⚠ Replay detected: cached AgentShield decision returned (no new evaluation).");
        }
        return result;
      })
      .then(() => Promise.all([refresh(activeAgentId, true), refreshChecklist(activeAgentId)]))
      .then(() => {
        setPage("approvals");
        toast("✓ HITL test submitted — approve in Approvals");
      })
      .catch((err) => toast(err.message || "Suspicious test failed"))
      .finally(() => setHitlRunning(false));
  };

  const addBlockedVendor = () => {
    const v = form.draftVendor.trim();
    if (!v) return;
    setForm((p) => ({ ...p, blocked: Array.from(new Set([...p.blocked, v])), draftVendor: "" }));
  };

  const addScope = () => {
    const scope = form.draftScope.trim();
    if (!scope) return;
    setForm((p) => ({ ...p, scopes: Array.from(new Set([...p.scopes, scope])), draftScope: "" }));
  };

  const removeScope = (scope) => {
    setForm((p) => ({ ...p, scopes: p.scopes.filter((item) => item !== scope) }));
  };

  const saveAgentScopes = async (scopes) => {
    if (!activeAgentId) return;
    try {
      setScopesSaving(true);
      await updateAgentScopes(activeAgentId, scopes);
      const data = await listAgents();
      setAgents(data.agents);
      toast("Goal scopes updated");
      await refresh(activeAgentId, true);
    } catch (err) {
      toast(err.message || "Could not update scopes");
    } finally {
      setScopesSaving(false);
    }
  };

  const saveAgentSettings = async (settingsPayload) => {
    if (!activeAgentId) return;
    try {
      setSettingsSaving(true);
      await updateAgentSettings(activeAgentId, settingsPayload);
      const data = await listAgents();
      setAgents(data.agents);
      toast("Agent settings updated");
      await refresh(activeAgentId, true);
    } catch (err) {
      toast(err.message || "Could not update agent settings");
    } finally {
      setSettingsSaving(false);
    }
  };

  const activeAgent = agents.find((agent) => agent.agent_id === activeAgentId) || null;
  const effectiveAgentId = activeAgentId || "agt_your_agent_id";
  const activeHmac = credsMap[activeAgentId] || "";
  const effectiveSecret = secretReveal ? (activeHmac || "<your-hmac-secret>") : "<your-hmac-secret>";
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

      <main style={{ flex: 1, overflowY: page === "docs" ? "hidden" : "auto", display: "flex", flexDirection: "column", background: "var(--bg)" }}>
        <header style={{ height: 48, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-1)" }}>{pageTitle}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {activeAgentId ? (
              <select
                value={activeAgentId}
                onChange={(e) => {
                  activeAgentRef.current = e.target.value;
                  setActiveAgentId(e.target.value);
                  refresh(e.target.value, true).catch(() => {});
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
            <button
              type="button"
              onClick={logout}
              style={{
                height: 28,
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-2)",
                padding: "0 8px",
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                cursor: "pointer",
              }}
            >
              Sign out
            </button>
          </div>
        </header>

        {page === "docs" ? (
          <div style={{ flex: 1, overflow: "hidden" }}>
            <DocsPage
              agentId={effectiveAgentId}
              activeHmac={activeHmac}
              secretReveal={secretReveal}
              setSecretReveal={setSecretReveal}
              apiBase={apiBase}
            />
          </div>
        ) : null}

        <section style={{ padding: 24, display: page === "docs" ? "none" : undefined }}>


          {page === "overview" ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
                {[
                  ["transactions", stats.total, activityMeta.countMode === "today_utc" ? "today (UTC)" : "current scope", "var(--text-1)"],
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
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: "var(--text-2)" }}>Request Activity</div>
                  <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--text-3)" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />safe</span>
                    <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", display: "inline-block" }} />pending</span>
                    <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)", display: "inline-block" }} />blocked</span>
                  </div>
                </div>
                <div style={{ height: 160 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
                      <XAxis dataKey="t" tick={{ fill: "var(--text-3)", fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis allowDecimals={false} tick={{ fill: "var(--text-3)", fontSize: 10 }} axisLine={false} tickLine={false} width={24} domain={[0, (dataMax) => Math.max(dataMax + 1, 3)]} />
                      <Tooltip
                        cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
                        contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)", fontSize: 11, fontFamily: "var(--font-mono)", padding: "4px 8px" }}
                        itemStyle={{ color: "var(--text-2)" }}
                        labelStyle={{ color: "var(--text-3)", marginBottom: 2 }}
                      />
                      <Line type="monotone" dataKey="safe" stroke="var(--green)" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: "var(--green)", strokeWidth: 0 }} connectNulls={true} />
                      <Line type="monotone" dataKey="pending" stroke="var(--amber)" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: "var(--amber)", strokeWidth: 0 }} connectNulls={true} />
                      <Line type="monotone" dataKey="blocked" stroke="var(--red)" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: "var(--red)", strokeWidth: 0 }} connectNulls={true} />
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
                <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
                  {activityMeta.countMode === "today_utc" ? "today_utc" : activityMeta.countMode} · total {activityMeta.totalToday}
                </div>
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
                            <div style={{ color: "var(--text-2)", fontSize: 11, margin: "6px 0 6px" }}>Check C · Semantic</div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>alignment score</span><span>{r.details.slm.score}</span></div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", marginBottom: 3 }}><span style={{ color: "var(--text-2)" }}>verdict</span><span>{r.details.slm.verdict}</span></div>
                            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr" }}><span style={{ color: "var(--text-2)" }}>reason</span><span>{r.details.slm.reason}</span></div>
                            <div style={{ color: "var(--text-2)", fontSize: 11, margin: "6px 0 6px" }}>Check D · Goal Drift</div>
                            {r.details.goalDrift.skipped ? (
                              <div style={{ color: "var(--text-3)" }}>skipped — no scopes defined</div>
                            ) : r.details.goalDrift.within_scope ? (
                              <div style={{ display: "grid", gridTemplateColumns: "140px 1fr" }}><span style={{ color: "var(--text-2)" }}>matched scope</span><span style={{ color: "var(--green)" }}>✓ {r.details.goalDrift.matched_scope || "within scope"}</span></div>
                            ) : (
                              <div style={{ color: "var(--red)" }}>✗ GOAL_DRIFT_DETECTED — {r.details.goalDrift.reason || "goal outside allowed scopes"}</div>
                            )}
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
                            <span style={{ color: "var(--text-2)" }}>Semantic Score</span>
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
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", marginBottom: 8 }}>
                            <span style={{ color: "var(--text-2)" }}>Policy</span>
                            <div>{a.policy.map((s) => <div key={s}>{s}</div>)}</div>
                          </div>
                          <div style={{ display: "grid", gridTemplateColumns: "84px 1fr" }}>
                            <span style={{ color: "var(--text-2)" }}>Goal Drift</span>
                            <div>
                              {a.goalDrift.skipped
                                ? <span style={{ color: "var(--text-3)" }}>skipped — no scopes</span>
                                : a.goalDrift.within_scope
                                  ? <span style={{ color: "var(--green)" }}>✓ {a.goalDrift.matched_scope || "within scope"}</span>
                                  : <span style={{ color: "var(--red)" }}>✗ drift — {a.goalDrift.reason || "outside allowed scopes"}</span>
                              }
                            </div>
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
            <AgentsPanel
              agents={agents}
              activeAgent={activeAgent}
              activeAgentId={activeAgentId}
              activeHmac={activeHmac}
              form={form}
              onFormChange={setForm}
              showSuccess={showSuccess}
              showNewAgentForm={showNewAgentForm}
              secretReveal={secretReveal}
              onToggleSecret={() => setSecretReveal((prev) => !prev)}
              onShowNewAgent={() => { setShowNewAgentForm(true); setShowSuccess(false); }}
              onHideNewAgent={() => { setShowNewAgentForm(false); setShowSuccess(false); }}
              onCreateAgent={handleCreateAgent}
              onAddBlockedVendor={addBlockedVendor}
              onAddScope={addScope}
              onRemoveScope={removeScope}
              onRunSafeTest={runSafeTest}
              onRunSuspiciousTest={runSuspiciousTest}
              safeRunning={safeRunning}
              hitlRunning={hitlRunning}
              onGoToActivity={() => setPage("activity")}
              onSaveScopes={saveAgentScopes}
              scopesSaving={scopesSaving}
              onSaveSettings={saveAgentSettings}
              settingsSaving={settingsSaving}
            />
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

