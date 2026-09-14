import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import App from "./App";
import "./index.css";
import { isAuthenticated } from "./lib/auth";
import AuthCallbackView from "./views/AuthCallbackView";
import AuthView from "./views/AuthView";
import LandingView from "./views/LandingView";

function RequireAuth({ children }) {
  const location = useLocation();
  if (!isAuthenticated()) {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={`/auth?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingView />} />
        <Route path="/auth" element={<AuthView />} />
        <Route path="/auth/callback" element={<AuthCallbackView />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <App />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);

