import { Link } from "react-router-dom";

// Shared chrome for /auth and /auth/callback so both screens read as the same
// product as the landing page.
export default function AuthShell({ label, title, subtitle, children, footer }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0c0c0c",
        color: "#ededed",
        fontFamily: "Geist, IBM Plex Sans, sans-serif",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <style>{`
        .auth-grid {
          position: fixed; inset: 0; pointer-events: none; z-index: 0;
          background-image: radial-gradient(circle, #1c1c1c 1px, transparent 1px);
          background-size: 28px 28px;
          mask-image: radial-gradient(ellipse 70% 70% at 50% 45%, black 35%, transparent 100%);
          -webkit-mask-image: radial-gradient(ellipse 70% 70% at 50% 45%, black 35%, transparent 100%);
        }
        .auth-mono { font-family: "Geist Mono", "IBM Plex Mono", monospace; }
        .auth-btn {
          width: 100%; height: 40px; display: inline-flex; align-items: center; justify-content: center;
          background: #ededed; color: #0c0c0c; border: 1px solid #ededed;
          font-family: "Geist Mono", monospace; font-size: 13px; letter-spacing: 0.02em;
          cursor: pointer; transition: opacity 100ms;
        }
        .auth-btn:hover:not(:disabled) { opacity: 0.85; }
        .auth-btn:disabled { opacity: 0.32; cursor: not-allowed; }
        .auth-btn-ghost {
          width: 100%; height: 38px; display: inline-flex; align-items: center; justify-content: center;
          background: transparent; color: #ccc; border: 1px solid #2a2a2a;
          font-family: "Geist Mono", monospace; font-size: 13px;
          cursor: pointer; transition: border-color 100ms, color 100ms;
        }
        .auth-btn-ghost:hover { border-color: #444; color: #ededed; }
        .auth-lnk { color: #949494; text-decoration: none; font-size: 13px; transition: color 100ms; }
        .auth-lnk:hover { color: #ccc; }
        .auth-note { border: 1px solid #242424; background: #101010; padding: 12px 14px; font-size: 12.5px; line-height: 1.6; color: #9a9a9a; }
        .auth-note-bad { border-color: #4a2424; background: #140f0f; color: #eaaaaa; }
        @keyframes authSpin { to { transform: rotate(360deg); } }
        .auth-spinner {
          width: 14px; height: 14px; border: 1.5px solid #2e2e2e; border-top-color: #ededed;
          border-radius: 50%; animation: authSpin 700ms linear infinite; display: inline-block;
        }
      `}</style>

      <div className="auth-grid" />

      <div style={{ position: "relative", zIndex: 1, minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <nav
          style={{
            borderBottom: "1px solid #161616",
            padding: "0 32px",
            height: 52,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Link to="/" className="auth-mono" style={{ fontSize: 12, color: "#ededed", letterSpacing: "0.08em", textDecoration: "none" }}>
            AGENTSHIELD
          </Link>
          <Link to="/" className="auth-lnk">
            Back to site
          </Link>
        </nav>

        <div style={{ flex: 1, display: "grid", placeItems: "center", padding: "32px 24px 64px" }}>
          <div style={{ width: "100%", maxWidth: 400 }}>
            <div className="auth-mono" style={{ fontSize: 10, letterSpacing: "0.12em", color: "#8a8a8a", marginBottom: 14 }}>
              {label}
            </div>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.15 }}>{title}</h1>
            {subtitle ? (
              <p style={{ margin: "12px 0 0", fontSize: 14, lineHeight: 1.65, color: "#a1a1a1" }}>{subtitle}</p>
            ) : null}
            <div style={{ marginTop: 26, display: "grid", gap: 12 }}>{children}</div>
            {footer ? <div style={{ marginTop: 22 }}>{footer}</div> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
