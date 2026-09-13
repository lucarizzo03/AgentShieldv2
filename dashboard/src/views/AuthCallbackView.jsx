import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { handleAuthCallback } from "../lib/auth";
import AuthShell from "./AuthShell";

export default function AuthCallbackView() {
  const location = useLocation();
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    handleAuthCallback(location.search)
      .then((returnTo) => {
        if (!active) return;
        navigate(returnTo, { replace: true });
      })
      .catch((err) => {
        if (!active) return;
        setError(err.message || "Authentication failed.");
      });
    return () => {
      active = false;
    };
  }, [location.search, navigate]);

  if (error) {
    return (
      <AuthShell label="SIGN IN — FAILED" title="Sign-in didn't complete" subtitle={error}>
        <Link to="/auth" className="auth-btn" style={{ textDecoration: "none" }}>
          Back to sign in
        </Link>
        <div className="auth-note">
          If this keeps happening, confirm this callback URL is listed in the Auth0 application's allowed callback
          URLs and that the API audience matches the dashboard configuration.
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell label="SIGN IN" title="Completing sign-in" subtitle="Exchanging your authorization code with Auth0.">
      <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#a1a1a1", fontSize: 13 }}>
        <span className="auth-spinner" />
        This should only take a second.
      </div>
    </AuthShell>
  );
}
