import { Link } from "react-router-dom";

import { loginWithDevToken } from "../lib/auth";

export default function AuthView() {
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
          Railway-only mode is enabled. Sign in with the local development session.
        </p>
        <button
          type="button"
          onClick={loginWithDevToken}
          style={{
            width: "100%",
            height: 38,
            marginTop: 8,
            border: "1px solid #2f4f2f",
            background: "#132013",
            color: "#d6f5d6",
            fontFamily: "Geist Mono, monospace",
            cursor: "pointer",
          }}
        >
          Use Local Dev Session
        </button>
        <p style={{ marginTop: 16, color: "#888", fontSize: 13 }}>
          <Link to="/" style={{ color: "#ccc" }}>
            Back to landing
          </Link>
        </p>
      </div>
    </div>
  );
}
