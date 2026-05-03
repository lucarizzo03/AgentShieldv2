import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { handleAuthCallback } from "../lib/auth";

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
        setError(err.message || "Authentication failed");
      });
    return () => {
      active = false;
    };
  }, [location.search, navigate]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#0c0c0c",
        color: "#ededed",
      }}
    >
      <div style={{ textAlign: "center" }}>
        {!error ? (
          <>
            <p style={{ margin: 0, fontSize: 18 }}>Completing sign-in...</p>
            <p style={{ color: "#888", marginTop: 8 }}>Please wait while we verify your session.</p>
          </>
        ) : (
          <>
            <p style={{ margin: 0, fontSize: 18 }}>Sign-in failed</p>
            <p style={{ color: "#ff7b7b", marginTop: 8 }}>{error}</p>
          </>
        )}
      </div>
    </div>
  );
}
