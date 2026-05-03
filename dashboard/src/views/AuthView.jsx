import { Link } from "react-router-dom";

import { isAuthConfigured, loginWithDevToken, startLogin } from "../lib/auth";

export default function AuthView() {
  const authConfigured = isAuthConfigured();
  const enableDevAuth = String(import.meta.env.VITE_ENABLE_DEV_AUTH || "false").toLowerCase() === "true";
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
          Sign in with Auth0 to access your agents and dashboard activity.
        </p>
        {!authConfigured ? (
          <div style={{ border: "1px solid #4a2", background: "#131a12", color: "#d7ffd2", padding: 10, fontSize: 13 }}>
            Auth0 is not configured. Set `VITE_AUTH0_DOMAIN`, `VITE_AUTH0_CLIENT_ID`, `VITE_AUTH0_AUDIENCE`,
            and `VITE_AUTH0_REDIRECT_URI` in dashboard variables.
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => startLogin()}
          disabled={!authConfigured}
          style={{
            width: "100%",
            height: 38,
            marginTop: 8,
            border: "1px solid #ededed",
            background: "#ededed",
            color: "#0c0c0c",
            fontFamily: "Geist Mono, monospace",
            cursor: authConfigured ? "pointer" : "not-allowed",
          }}
        >
          Continue with Auth0
        </button>
        {enableDevAuth ? (
          <button
            type="button"
            onClick={loginWithDevToken}
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
