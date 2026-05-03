import { Link } from "react-router-dom";

import { isAuthConfigured, startLogin } from "../lib/auth";

export default function AuthView() {
  const configured = isAuthConfigured();
  const devToken = import.meta.env.VITE_DEV_USER_TOKEN || "dev-user-token";

  async function handleEmailLogin() {
    await startLogin();
  }

  async function handleGoogleLogin() {
    await startLogin({ provider: "Google" });
  }

  function handleLocalDevLogin() {
    localStorage.setItem("agentshield_id_token", devToken);
    window.location.assign("/app");
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#0c0c0c",
        color: "#ededed",
        padding: 24,
      }}
    >
      <div style={{ width: "100%", maxWidth: 420, border: "1px solid #222", background: "#111", padding: 20 }}>
        <h1 style={{ margin: 0, marginBottom: 6, fontSize: 24 }}>Sign in to AgentShield</h1>
        <p style={{ marginTop: 0, marginBottom: 18, color: "#888", fontSize: 14 }}>
          Use email/password or Google through AWS Cognito.
        </p>
        {!configured ? (
          <div style={{ border: "1px solid #4a2", background: "#131a12", color: "#d7ffd2", padding: 10, fontSize: 13 }}>
            Cognito is not configured. Set `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_CLIENT_ID`, and
            `VITE_COGNITO_REDIRECT_URI` in dashboard env.
          </div>
        ) : null}
        <button
          type="button"
          onClick={handleEmailLogin}
          disabled={!configured}
          style={{
            width: "100%",
            height: 38,
            marginTop: 8,
            border: "1px solid #ededed",
            background: "#ededed",
            color: "#0c0c0c",
            fontFamily: "Geist Mono, monospace",
            cursor: configured ? "pointer" : "not-allowed",
          }}
        >
          Continue with Email
        </button>
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={!configured}
          style={{
            width: "100%",
            height: 38,
            marginTop: 10,
            border: "1px solid #333",
            background: "transparent",
            color: "#ededed",
            fontFamily: "Geist Mono, monospace",
            cursor: configured ? "pointer" : "not-allowed",
          }}
        >
          Continue with Google
        </button>
        {!configured ? (
          <button
            type="button"
            onClick={handleLocalDevLogin}
            style={{
              width: "100%",
              height: 34,
              marginTop: 10,
              border: "1px solid #2f4f2f",
              background: "#132013",
              color: "#d6f5d6",
              fontFamily: "Geist Mono, monospace",
              cursor: "pointer",
            }}
          >
            Use Local Dev Session
          </button>
        ) : null}
        <p style={{ marginTop: 16, color: "#888", fontSize: 13 }}>
          <Link to="/" style={{ color: "#ccc" }}>
            Back to landing
          </Link>
        </p>
      </div>
    </div>
  );
}
