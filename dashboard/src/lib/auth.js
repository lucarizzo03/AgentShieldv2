const AUTH_STORAGE_KEY = "agentshield_id_token";
const PKCE_VERIFIER_KEY = "agentshield_pkce_verifier";
const RETURN_TO_KEY = "agentshield_return_to";

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(length = 64) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"[b % 66]).join("");
}

async function pkceChallengeFromVerifier(verifier) {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(digest);
}

export function getAuthConfig() {
  const domain = (import.meta.env.VITE_COGNITO_DOMAIN || "").replace(/\/$/, "");
  return {
    domain,
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || "",
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI || `${window.location.origin}/auth/callback`,
    logoutUri: import.meta.env.VITE_COGNITO_LOGOUT_URI || `${window.location.origin}/`,
    scopes: import.meta.env.VITE_COGNITO_SCOPES || "openid email profile",
  };
}

export function isAuthConfigured() {
  const cfg = getAuthConfig();
  return Boolean(cfg.domain && cfg.clientId && cfg.redirectUri);
}

export function getIdToken() {
  return localStorage.getItem(AUTH_STORAGE_KEY);
}

export function isAuthenticated() {
  return Boolean(getIdToken());
}

export function clearAuthSession() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
}

export async function startLogin({ provider, returnTo = "/app" } = {}) {
  const cfg = getAuthConfig();
  if (!isAuthConfigured()) {
    throw new Error("Cognito auth is not configured.");
  }

  const verifier = randomString(64);
  const challenge = await pkceChallengeFromVerifier(verifier);
  const state = randomString(24);

  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(RETURN_TO_KEY, returnTo);

  const url = new URL(`${cfg.domain}/oauth2/authorize`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", cfg.clientId);
  url.searchParams.set("redirect_uri", cfg.redirectUri);
  url.searchParams.set("scope", cfg.scopes);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  if (provider) {
    url.searchParams.set("identity_provider", provider);
  }

  window.location.assign(url.toString());
}

export async function handleAuthCallback(search) {
  const cfg = getAuthConfig();
  const params = new URLSearchParams(search);
  const code = params.get("code");
  const error = params.get("error");
  const errorDescription = params.get("error_description");
  if (error) {
    throw new Error(errorDescription || error);
  }
  if (!code) {
    throw new Error("Authorization code is missing.");
  }

  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
  if (!verifier) {
    throw new Error("Missing PKCE verifier.");
  }

  const body = new URLSearchParams();
  body.set("grant_type", "authorization_code");
  body.set("client_id", cfg.clientId);
  body.set("code", code);
  body.set("redirect_uri", cfg.redirectUri);
  body.set("code_verifier", verifier);

  const response = await fetch(`${cfg.domain}/oauth2/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });
  if (!response.ok) {
    throw new Error(`Token exchange failed (${response.status})`);
  }

  const payload = await response.json();
  if (!payload.id_token) {
    throw new Error("Missing id_token in Cognito response.");
  }
  localStorage.setItem(AUTH_STORAGE_KEY, payload.id_token);

  const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || "/app";
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return returnTo;
}

export function logout() {
  const cfg = getAuthConfig();
  clearAuthSession();
  if (!cfg.domain || !cfg.clientId) {
    window.location.assign("/");
    return;
  }
  const logoutUrl = new URL(`${cfg.domain}/logout`);
  logoutUrl.searchParams.set("client_id", cfg.clientId);
  logoutUrl.searchParams.set("logout_uri", cfg.logoutUri);
  window.location.assign(logoutUrl.toString());
}
