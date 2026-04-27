const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/v1";

export function authHeaders(agentId, extra = {}) {
  return {
    "Content-Type": "application/json",
    "x-agent-key": "local-dev-key",
    ...(agentId ? { "x-agent-id": agentId } : {}),
    ...extra,
  };
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // noop
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function listAgents() {
  return request("/agents");
}

export async function createAgent(payload) {
  return request("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getDashboardStats(agentId) {
  return request(`/dashboard/agents/${agentId}/stats`, {
    headers: authHeaders(agentId),
  });
}

export async function getActivity(agentId) {
  return request(`/dashboard/agents/${agentId}/activity?limit=100`, {
    headers: authHeaders(agentId),
  });
}

export async function getNotifications(agentId) {
  return request(`/dashboard/agents/${agentId}/notifications?status=OPEN&limit=50`, {
    headers: authHeaders(agentId),
  });
}

export async function resolveRequest(requestId, decision, resolverId = "dashboard:operator") {
  return request(`/hitl/resolve/${requestId}`, {
    method: "POST",
    headers: {
      ...authHeaders(undefined),
      "x-webhook-signature": "sig_ok",
    },
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
  });
}

export async function bootstrapOnboarding(payload) {
  return request("/onboarding/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getOnboardingChecklist(agentId) {
  return request(`/onboarding/agents/${agentId}/checklist`, {
    headers: authHeaders(agentId),
  });
}

export async function startPhoneVerification(agentId, phoneNumber) {
  return request(`/agents/${agentId}/contact/phone/start`, {
    method: "POST",
    headers: authHeaders(agentId),
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
}

export async function verifyPhone(agentId, phoneNumber, code) {
  return request(`/agents/${agentId}/contact/phone/verify`, {
    method: "POST",
    headers: authHeaders(agentId),
    body: JSON.stringify({ phone_number: phoneNumber, code }),
  });
}

export async function updateHitlPreferences(agentId, prefs) {
  return request(`/agents/${agentId}/preferences/hitl`, {
    method: "PATCH",
    headers: authHeaders(agentId),
    body: JSON.stringify(prefs),
  });
}

export async function getAgent(agentId) {
  const data = await listAgents();
  return data.agents.find((a) => a.agent_id === agentId) || null;
}

