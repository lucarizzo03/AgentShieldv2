const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/v1";
const AUTH_STORAGE_KEY = "agentshield_id_token";

export function authHeaders(agentId, extra = {}) {
  return {
    "Content-Type": "application/json",
    ...(agentId ? { "x-agent-id": agentId } : {}),
    ...extra,
  };
}

async function request(path, options = {}) {
  const { authMode = "user", headers = {}, ...rest } = options;
  const finalHeaders = { ...headers };
  if (authMode === "user") {
    const token = localStorage.getItem(AUTH_STORAGE_KEY);
    if (token && !finalHeaders.Authorization) {
      finalHeaders.Authorization = `Bearer ${token}`;
    }
  }
  const response = await fetch(`${API_BASE}${path}`, { ...rest, headers: finalHeaders });
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const data = await response.json();
      const detail = data.detail;
      message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((e) => e.msg || JSON.stringify(e)).join("; ") : message;
    } catch {
      // noop
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function listAgents() {
  return request("/agents", { authMode: "user" });
}

export async function createAgent(payload) {
  return request("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    authMode: "user",
  });
}

export async function getDashboardStats(agentId) {
  return request(`/dashboard/agents/${agentId}/stats`, {
    authMode: "user",
  });
}

export async function getActivity(agentId) {
  return request(`/dashboard/agents/${agentId}/activity?limit=100`, {
    authMode: "user",
  });
}

export async function getNotifications(agentId) {
  return request(`/dashboard/agents/${agentId}/notifications?status=OPEN&limit=50`, {
    authMode: "user",
  });
}

export async function resolveRequest(requestId, decision, resolverId = "dashboard:operator") {
  return request(`/hitl/resolve/${requestId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    authMode: "user",
    body: JSON.stringify({
      decision,
      resolver_id: resolverId,
      channel: "dashboard",
    }),
  });
}

export async function submitSpendRequest(agentId, payload) {
  return request("/spend-request", {
    method: "POST",
    headers: authHeaders(agentId),
    body: JSON.stringify(payload),
    authMode: "none",
  });
}

// Used by dashboard mock test buttons — authenticates with the operator's
// Bearer token so no HMAC signing is required.
export async function runDevTestRequest(agentId, payload) {
  return request("/spend-request", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-agent-id": agentId },
    body: JSON.stringify(payload),
    authMode: "user",
  });
}

export async function bootstrapOnboarding(payload) {
  return request("/onboarding/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    authMode: "none",
  });
}

export async function getOnboardingChecklist(agentId) {
  return request(`/onboarding/agents/${agentId}/checklist`, {
    headers: authHeaders(agentId),
    authMode: "none",
  });
}

export async function startPhoneVerification(agentId, phoneNumber) {
  return request(`/agents/${agentId}/contact/phone/start`, {
    method: "POST",
    headers: authHeaders(agentId),
    body: JSON.stringify({ phone_number: phoneNumber }),
    authMode: "none",
  });
}

export async function verifyPhone(agentId, phoneNumber, code) {
  return request(`/agents/${agentId}/contact/phone/verify`, {
    method: "POST",
    headers: authHeaders(agentId),
    body: JSON.stringify({ phone_number: phoneNumber, code }),
    authMode: "none",
  });
}

export async function updateHitlPreferences(agentId, prefs) {
  return request(`/agents/${agentId}/preferences/hitl`, {
    method: "PATCH",
    headers: authHeaders(agentId),
    body: JSON.stringify(prefs),
    authMode: "none",
  });
}

export async function getAgent(agentId) {
  const data = await listAgents();
  return data.agents.find((a) => a.agent_id === agentId) || null;
}

export async function updateAgentScopes(agentId, allowedScopes) {
  return request(`/agents/${agentId}/scopes`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allowed_scopes: allowedScopes }),
    authMode: "user",
  });
}

