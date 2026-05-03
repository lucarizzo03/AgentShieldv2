import { Link } from "react-router-dom";

export default function LandingView() {
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
      <div style={{ maxWidth: 760, width: "100%", textAlign: "center" }}>
        <p style={{ color: "#888", fontFamily: "Geist Mono, monospace", letterSpacing: "0.08em" }}>
          AGENTSHIELD
        </p>
        <h1 style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)", margin: "8px 0 12px" }}>
          Autonomous Agent Spending Firewall
        </h1>
        <p style={{ color: "#aaa", fontSize: 18, lineHeight: 1.5, margin: "0 auto 28px" }}>
          Detect suspicious agent transactions, route high-risk decisions to human review, and keep
          real-time policy visibility in one dashboard.
        </p>
        <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
          <Link
            to="/auth"
            style={{
              textDecoration: "none",
              color: "#0c0c0c",
              background: "#ededed",
              border: "1px solid #ededed",
              padding: "10px 18px",
              fontFamily: "Geist Mono, monospace",
              fontSize: 13,
            }}
          >
            Get Started
          </Link>
          <a
            href="https://github.com/lucarizzo03/AgentShieldv2"
            target="_blank"
            rel="noreferrer"
            style={{
              textDecoration: "none",
              color: "#ededed",
              border: "1px solid #333",
              padding: "10px 18px",
              fontFamily: "Geist Mono, monospace",
              fontSize: 13,
            }}
          >
            View GitHub
          </a>
        </div>
      </div>
    </div>
  );
}
