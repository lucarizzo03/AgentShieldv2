import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import "./index.css";
import { isAuthenticated } from "./lib/auth";
import AuthView from "./views/AuthView";
import LandingView from "./views/LandingView";

function RequireAuth({ children }) {
  if (!isAuthenticated()) {
    return <Navigate to="/auth" replace />;
  }
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingView />} />
        <Route path="/auth" element={<AuthView />} />
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

