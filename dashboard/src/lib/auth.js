const AUTH_STORAGE_KEY = "agentshield_id_token";
const PKCE_VERIFIER_KEY = "agentshield_pkce_verifier";
const PKCE_STATE_KEY = "agentshield_pkce_state";
const RETURN_TO_KEY = "agentshield_return_to";

// A callback URL can be replayed by React StrictMode's double effect, a refresh
// or a back navigation. Auth0 only honours an authorization code once, so the
// exchange is deduplicated per code and its result replayed.
const inFlightExchanges = new Map();

function decodeJwtPayload(token) {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), "=");
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(length = 64) {
  const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => charset[b % charset.length]).join("");
}

async function pkceChallengeFromVerifier(verifier) {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(digest);
}

export function getAuthConfig() {
  const domain = (import.meta.env.VITE_AUTH0_DOMAIN || "").replace(/\/$/, "");
  return {
    domain: domain.startsWith("https://") ? domain : domain ? `https://${domain}` : "",
    clientId: import.meta.env.VITE_AUTH0_CLIENT_ID || "",
    audience: import.meta.env.VITE_AUTH0_AUDIENCE || "",
    redirectUri: import.meta.env.VITE_AUTH0_REDIRECT_URI || `${window.location.origin}/auth/callback`,
    logoutUri: import.meta.env.VITE_AUTH0_LOGOUT_URI || `${window.location.origin}/`,
    scopes: import.meta.env.VITE_AUTH0_SCOPES || "openid profile email",
  };
}

export function isAuthConfigured() {
  const cfg = getAuthConfig();
  return Boolean(cfg.domain && cfg.clientId && cfg.redirectUri && cfg.audience);
}

export function getIdToken() {
  return localStorage.getItem(AUTH_STORAGE_KEY);
}

export function isTokenExpired(token, leewaySeconds = 30) {
  if (!token) return true;
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") {
    return true;
  }
  const nowSeconds = Math.floor(Date.now() / 1000);
  return exp <= nowSeconds + leewaySeconds;
}

export function getSessionProfile() {
  const payload = decodeJwtPayload(getIdToken() || "");
  if (!payload) return null;
  return {
    sub: typeof payload.sub === "string" ? payload.sub : null,
    email: typeof payload.email === "string" ? payload.email : null,
    expiresAt: typeof payload.exp === "number" ? payload.exp : null,
  };
}

export function isAuthenticated() {
  return !isTokenExpired(getIdToken());
}

export function clearAuthSession() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
}

export function missingAuthConfigKeys() {
  const cfg = getAuthConfig();
  return [
    ["VITE_AUTH0_DOMAIN", cfg.domain],
    ["VITE_AUTH0_CLIENT_ID", cfg.clientId],
    ["VITE_AUTH0_AUDIENCE", cfg.audience],
    ["VITE_AUTH0_REDIRECT_URI", cfg.redirectUri],
  ]
    .filter(([, value]) => !value)
    .map(([name]) => name);
}

export async function startLogin({ returnTo = "/app" } = {}) {
  const cfg = getAuthConfig();
  if (!isAuthConfigured()) {
    throw new Error("Auth0 is not configured.");
  }
  const verifier = randomString(64);
  const challenge = await pkceChallengeFromVerifier(verifier);
  const state = randomString(24);

  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(PKCE_STATE_KEY, state);
  sessionStorage.setItem(RETURN_TO_KEY, returnTo);

  const authorize = new URL(`${cfg.domain}/authorize`);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("client_id", cfg.clientId);
  authorize.searchParams.set("redirect_uri", cfg.redirectUri);
  authorize.searchParams.set("scope", cfg.scopes);
  authorize.searchParams.set("audience", cfg.audience);
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("code_challenge", challenge);
  authorize.searchParams.set("code_challenge_method", "S256");
  window.location.assign(authorize.toString());
}

export async function handleAuthCallback(search) {
  const params = new URLSearchParams(search);
  const code = params.get("code");
  const error = params.get("error");
  const errorDescription = params.get("error_description");
  if (error) {
    throw new Error(errorDescription || error);
  }
  if (!code) {
    throw new Error("Authorization code missing from the Auth0 redirect.");
  }
  const pending = inFlightExchanges.get(code);
  if (pending) return pending;

  const exchange = exchangeCodeForToken(code, params.get("state"));
  inFlightExchanges.set(code, exchange);
  exchange.catch(() => inFlightExchanges.delete(code));
  return exchange;
}

async function exchangeCodeForToken(code, returnedState) {
  const cfg = getAuthConfig();
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
  const expectedState = sessionStorage.getItem(PKCE_STATE_KEY);
  if (!verifier || !expectedState) {
    throw new Error("This sign-in link is no longer valid. Start over from the sign-in page.");
  }
  if (returnedState !== expectedState) {
    clearAuthSession();
    throw new Error("Sign-in state did not match. Start over from the sign-in page.");
  }

  const tokenPayload = {
    grant_type: "authorization_code",
    client_id: cfg.clientId,
    code,
    redirect_uri: cfg.redirectUri,
    code_verifier: verifier,
  };

  const response = await fetch(`${cfg.domain}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tokenPayload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      detail?.error_description || `Auth0 rejected the token exchange (${response.status}).`
    );
  }
  const data = await response.json();
  const accessToken = data.access_token;
  if (!accessToken) {
    throw new Error("Auth0 returned no access token. Check the API audience configuration.");
  }
  if (isTokenExpired(accessToken, 0)) {
    throw new Error("Auth0 returned a token this dashboard cannot read. Check the API audience configuration.");
  }
  localStorage.setItem(AUTH_STORAGE_KEY, accessToken);

  const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || "/app";
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return returnTo;
}

export function devAuthToken() {
  if (String(import.meta.env.VITE_ENABLE_DEV_AUTH || "false").toLowerCase() !== "true") return "";
  return import.meta.env.VITE_DEV_USER_TOKEN || "";
}

export function loginWithDevToken() {
  const token = devAuthToken();
  if (!token) {
    throw new Error("Set VITE_DEV_USER_TOKEN to a token the API accepts to use a local dev session.");
  }
  localStorage.setItem(AUTH_STORAGE_KEY, token);
  window.location.assign("/app");
}

export function logout() {
  const cfg = getAuthConfig();
  clearAuthSession();
  if (isAuthConfigured()) {
    const logoutUrl = new URL(`${cfg.domain}/v2/logout`);
    logoutUrl.searchParams.set("client_id", cfg.clientId);
    logoutUrl.searchParams.set("returnTo", cfg.logoutUri);
    window.location.assign(logoutUrl.toString());
    return;
  }
  window.location.assign("/");
}
