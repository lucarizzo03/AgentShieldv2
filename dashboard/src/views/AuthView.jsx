import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import {
  devAuthToken,
  isAuthenticated,
  isAuthConfigured,
  loginWithDevToken,
  missingAuthConfigKeys,
  startLogin,
} from "../lib/auth";
import AuthShell from "./AuthShell";

function safeReturnTo(raw) {
  // Only same-origin paths, so a crafted ?returnTo cannot bounce the user off-site.
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/app";
  if (raw.startsWith("/auth")) return "/app";
  return raw;
}

export default function AuthView() {
  const [params] = useSearchParams();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const returnTo = safeReturnTo(params.get("returnTo"));
  const authConfigured = isAuthConfigured();
  const missingKeys = missingAuthConfigKeys();
  const devToken = devAuthToken();

  if (isAuthenticated()) {
    return <Navigate to={returnTo} replace />;
  }

  async function onLogin() {
    setError("");
    setPending(true);
    try {
      await startLogin({ returnTo });
    } catch (err) {
      setPending(false);
      setError(err.message || "Could not start sign-in.");
    }
  }

  function onDevLogin() {
    setError("");
    try {
      loginWithDevToken();
    } catch (err) {
      setError(err.message || "Could not start a local dev session.");
    }
  }

  return (
    <AuthShell
      label="SIGN IN"
      title="Sign in to AgentShield"
      subtitle="Auth0 handles the login. Your agents, spend activity, and approval queue live behind it."
      footer={
        <p className="auth-mono" style={{ margin: 0, fontSize: 11, color: "#858585", letterSpacing: "0.06em" }}>
          AUTHORIZATION CODE + PKCE
        </p>
      }
    >
      {error ? <div className="auth-note auth-note-bad">{error}</div> : null}

      {!authConfigured ? (
        <div className="auth-note">
          Auth0 is not configured for this deployment. Missing{" "}
          <span className="auth-mono" style={{ color: "#ededed" }}>
            {missingKeys.join(", ")}
          </span>
          .
        </div>
      ) : null}

      <button type="button" className="auth-btn" onClick={onLogin} disabled={!authConfigured || pending}>
        {pending ? (
          <>
            <span className="auth-spinner" style={{ marginRight: 10 }} />
            Redirecting to Auth0
          </>
        ) : (
          "Continue with Auth0"
        )}
      </button>

      {devToken ? (
        <button type="button" className="auth-btn-ghost" onClick={onDevLogin}>
          Use local dev session
        </button>
      ) : null}
    </AuthShell>
  );
}
