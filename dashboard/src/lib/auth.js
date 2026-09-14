const AUTH_STORAGE_KEY = "agentshield_id_token";
const PKCE_VERIFIER_KEY = "agentshield_pkce_verifier";
const PKCE_STATE_KEY = "agentshield_pkce_state";
const RETURN_TO_KEY = "agentshield_return_to";
const REFRESH_STORAGE_KEY = "agentshield_refresh_token";

// A callback URL can be replayed by React StrictMode's double effect, a refresh
// or a back navigation. Cognito only honours an authorization code once, so the
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
  const domain = (import.meta.env.VITE_COGNITO_DOMAIN || "").replace(/\/$/, "");
  return {
    domain: domain.startsWith("https://") ? domain : domain ? `https://${domain}` : "",
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || "",
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI || `${window.location.origin}/auth/callback`,
    logoutUri: import.meta.env.VITE_COGNITO_LOGOUT_URI || `${window.location.origin}/`,
    scopes: import.meta.env.VITE_COGNITO_SCOPES || "openid profile email",
  };
}

export function isAuthConfigured() {
  const cfg = getAuthConfig();
  return Boolean(cfg.domain && cfg.clientId && cfg.redirectUri);
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
  localStorage.removeItem(REFRESH_STORAGE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
}

export function missingAuthConfigKeys() {
  const cfg = getAuthConfig();
  return [
    ["VITE_COGNITO_DOMAIN", cfg.domain],
    ["VITE_COGNITO_CLIENT_ID", cfg.clientId],
    ["VITE_COGNITO_REDIRECT_URI", cfg.redirectUri],
  ]
    .filter(([, value]) => !value)
    .map(([name]) => name);
}

export async function startLogin({ returnTo = "/app" } = {}) {
  const cfg = getAuthConfig();
  if (!isAuthConfigured()) {
    throw new Error("Cognito is not configured.");
  }
  const verifier = randomString(64);
  const challenge = await pkceChallengeFromVerifier(verifier);
  const state = randomString(24);

  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(PKCE_STATE_KEY, state);
  sessionStorage.setItem(RETURN_TO_KEY, returnTo);

  const authorize = new URL(`${cfg.domain}/oauth2/authorize`);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("client_id", cfg.clientId);
  authorize.searchParams.set("redirect_uri", cfg.redirectUri);
  authorize.searchParams.set("scope", cfg.scopes);
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
    throw new Error("Authorization code missing from the Cognito redirect.");
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

  const response = await fetch(`${cfg.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(tokenPayload).toString(),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      detail?.error_description || `Cognito rejected the token exchange (${response.status}).`
    );
  }
  const data = await response.json();
  const accessToken = data.access_token;
  if (!accessToken) {
    throw new Error("Cognito returned no access token. Check the app client's allowed OAuth scopes.");
  }
  if (isTokenExpired(accessToken, 0)) {
    throw new Error("Cognito returned a token this dashboard cannot read.");
  }
  localStorage.setItem(AUTH_STORAGE_KEY, accessToken);

  const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || "/app";
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return returnTo;
}

// --- Native (in-app) Cognito auth ------------------------------------------
// Talks to the Cognito IdP API directly so the dashboard renders its own
// sign-in UI instead of bouncing through the hosted page. Requires
// ALLOW_USER_PASSWORD_AUTH on the app client and VITE_COGNITO_REGION.

function cognitoIdpEndpoint() {
  const region = import.meta.env.VITE_COGNITO_REGION || "";
  return region ? `https://cognito-idp.${region}.amazonaws.com/` : "";
}

export function isNativeAuthConfigured() {
  return Boolean(cognitoIdpEndpoint() && getAuthConfig().clientId);
}

const COGNITO_ERROR_MESSAGES = {
  NotAuthorizedException: "Incorrect email or password.",
  UserNotFoundException: "Incorrect email or password.",
  UserNotConfirmedException: "Confirm your email before signing in.",
  UsernameExistsException: "An account with this email already exists.",
  CodeMismatchException: "That code is incorrect.",
  ExpiredCodeException: "That code has expired. Request a new one.",
  InvalidPasswordException: "Password does not meet the requirements.",
  LimitExceededException: "Too many attempts. Wait a few minutes and try again.",
  TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
  InvalidParameterException: "Check the details you entered and try again.",
};

export class CognitoError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

async function cognitoCall(action, body) {
  const endpoint = cognitoIdpEndpoint();
  if (!endpoint) throw new CognitoError("NotConfigured", "Set VITE_COGNITO_REGION to enable sign-in.");
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = String(data.__type || data.code || "UnknownError").split("#").pop();
    const message =
      code === "InvalidPasswordException" && data.message
        ? data.message.replace(/^Password did not conform with policy:\s*/i, "")
        : COGNITO_ERROR_MESSAGES[code] || data.message || "Something went wrong. Try again.";
    throw new CognitoError(code, message);
  }
  return data;
}

function storeTokens(result) {
  const accessToken = result?.AccessToken;
  if (!accessToken || isTokenExpired(accessToken, 0)) {
    throw new CognitoError("BadToken", "Cognito returned a token this dashboard cannot read.");
  }
  localStorage.setItem(AUTH_STORAGE_KEY, accessToken);
  if (result.RefreshToken) localStorage.setItem(REFRESH_STORAGE_KEY, result.RefreshToken);
}

// Resolves to { status: "ok" } or { status: "challenge", challenge, session, email }.
export async function signIn(email, password) {
  const { clientId } = getAuthConfig();
  const data = await cognitoCall("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: clientId,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  if (data.ChallengeName) {
    return { status: "challenge", challenge: data.ChallengeName, session: data.Session, email };
  }
  storeTokens(data.AuthenticationResult);
  return { status: "ok" };
}

export async function completeNewPassword({ email, session, newPassword }) {
  const { clientId } = getAuthConfig();
  const data = await cognitoCall("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    ClientId: clientId,
    Session: session,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: newPassword },
  });
  if (data.ChallengeName) {
    return { status: "challenge", challenge: data.ChallengeName, session: data.Session, email };
  }
  storeTokens(data.AuthenticationResult);
  return { status: "ok" };
}

export async function signUp(email, password) {
  const { clientId } = getAuthConfig();
  const data = await cognitoCall("SignUp", {
    ClientId: clientId,
    Username: email,
    Password: password,
    UserAttributes: [{ Name: "email", Value: email }],
  });
  return { confirmed: Boolean(data.UserConfirmed) };
}

export async function confirmSignUp(email, code) {
  const { clientId } = getAuthConfig();
  await cognitoCall("ConfirmSignUp", { ClientId: clientId, Username: email, ConfirmationCode: code });
}

export async function resendConfirmationCode(email) {
  const { clientId } = getAuthConfig();
  await cognitoCall("ResendConfirmationCode", { ClientId: clientId, Username: email });
}

export async function forgotPassword(email) {
  const { clientId } = getAuthConfig();
  await cognitoCall("ForgotPassword", { ClientId: clientId, Username: email });
}

export async function confirmForgotPassword({ email, code, newPassword }) {
  const { clientId } = getAuthConfig();
  await cognitoCall("ConfirmForgotPassword", {
    ClientId: clientId,
    Username: email,
    ConfirmationCode: code,
    Password: newPassword,
  });
}

export async function refreshSession() {
  const refreshToken = localStorage.getItem(REFRESH_STORAGE_KEY);
  if (!refreshToken || !isNativeAuthConfigured()) return false;
  try {
    const data = await cognitoCall("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      ClientId: getAuthConfig().clientId,
      AuthParameters: { REFRESH_TOKEN: refreshToken },
    });
    storeTokens(data.AuthenticationResult);
    return true;
  } catch {
    localStorage.removeItem(REFRESH_STORAGE_KEY);
    return false;
  }
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
  const hadNativeSession = Boolean(localStorage.getItem(REFRESH_STORAGE_KEY));
  clearAuthSession();
  if (isAuthConfigured() && !hadNativeSession) {
    const logoutUrl = new URL(`${cfg.domain}/logout`);
    logoutUrl.searchParams.set("client_id", cfg.clientId);
    logoutUrl.searchParams.set("logout_uri", cfg.logoutUri);
    window.location.assign(logoutUrl.toString());
    return;
  }
  window.location.assign("/");
}
