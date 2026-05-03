const AUTH_STORAGE_KEY = "agentshield_id_token";

export function getIdToken() {
  return localStorage.getItem(AUTH_STORAGE_KEY);
}

export function isAuthenticated() {
  return Boolean(getIdToken());
}

export function clearAuthSession() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function loginWithDevToken() {
  const token = import.meta.env.VITE_DEV_USER_TOKEN || "dev-user-token";
  localStorage.setItem(AUTH_STORAGE_KEY, token);
  window.location.assign("/app");
}

export function logout() {
  clearAuthSession();
  window.location.assign("/");
}
