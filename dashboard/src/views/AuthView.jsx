import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import {
  completeNewPassword,
  confirmForgotPassword,
  confirmSignUp,
  devAuthToken,
  forgotPassword,
  isAuthenticated,
  isAuthConfigured,
  isNativeAuthConfigured,
  loginWithDevToken,
  missingAuthConfigKeys,
  resendConfirmationCode,
  signIn,
  signUp,
  startLogin,
} from "../lib/auth";
import AuthShell from "./AuthShell";

function safeReturnTo(raw) {
  // Only same-origin paths, so a crafted ?returnTo cannot bounce the user off-site.
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/app";
  if (raw.startsWith("/auth")) return "/app";
  return raw;
}

const COPY = {
  signin: { label: "SIGN IN", title: "Sign in to AgentShield", subtitle: "Your agents, spend activity, and approval queue live behind this door." },
  signup: { label: "CREATE ACCOUNT", title: "Create your account", subtitle: "We'll email you a verification code to finish setting up." },
  confirm: { label: "VERIFY EMAIL", title: "Check your inbox", subtitle: "Enter the 6-digit code we sent to confirm your email." },
  forgot: { label: "RESET PASSWORD", title: "Forgot your password?", subtitle: "We'll send a reset code to your email." },
  reset: { label: "RESET PASSWORD", title: "Choose a new password", subtitle: "Enter the code from your email along with a new password." },
  newpass: { label: "UPDATE PASSWORD", title: "Set a new password", subtitle: "Your account was created with a temporary password. Pick a permanent one to continue." },
};

function Field({ label, children }) {
  return (
    <label className="auth-field">
      <span className="auth-label">{label}</span>
      {children}
    </label>
  );
}

function SubmitButton({ pending, children, pendingLabel }) {
  return (
    <button type="submit" className="auth-btn" disabled={pending}>
      {pending ? (
        <>
          <span className="auth-spinner" style={{ marginRight: 10 }} />
          {pendingLabel}
        </>
      ) : (
        children
      )}
    </button>
  );
}

export default function AuthView() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const returnTo = safeReturnTo(params.get("returnTo"));

  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [challengeSession, setChallengeSession] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const nativeConfigured = isNativeAuthConfigured();
  const hostedConfigured = isAuthConfigured();
  const devToken = devAuthToken();

  if (isAuthenticated()) {
    return <Navigate to={returnTo} replace />;
  }

  function switchMode(next) {
    setMode(next);
    setError("");
    setNotice("");
    setPassword("");
    setConfirmPassword("");
    setCode("");
  }

  async function run(action) {
    setError("");
    setNotice("");
    setPending(true);
    try {
      await action();
    } catch (err) {
      setError(err.message || "Something went wrong. Try again.");
    } finally {
      setPending(false);
    }
  }

  function finishSignIn(result) {
    if (result.status === "ok") {
      navigate(returnTo, { replace: true });
      return;
    }
    if (result.challenge === "NEW_PASSWORD_REQUIRED") {
      setChallengeSession(result.session);
      switchMode("newpass");
      return;
    }
    throw new Error(`This account requires ${result.challenge}, which the dashboard does not support yet.`);
  }

  const onSignIn = (e) => {
    e.preventDefault();
    run(async () => {
      try {
        finishSignIn(await signIn(email.trim(), password));
      } catch (err) {
        if (err.code === "UserNotConfirmedException") {
          await resendConfirmationCode(email.trim()).catch(() => {});
          switchMode("confirm");
          setNotice("Your email isn't verified yet. We've sent you a new code.");
          return;
        }
        throw err;
      }
    });
  };

  const onSignUp = (e) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    run(async () => {
      const { confirmed } = await signUp(email.trim(), password);
      if (confirmed) {
        finishSignIn(await signIn(email.trim(), password));
        return;
      }
      switchMode("confirm");
      setNotice(`We sent a verification code to ${email.trim()}.`);
    });
  };

  const onConfirm = (e) => {
    e.preventDefault();
    run(async () => {
      await confirmSignUp(email.trim(), code.trim());
      if (password) {
        finishSignIn(await signIn(email.trim(), password));
        return;
      }
      switchMode("signin");
      setNotice("Email verified. Sign in to continue.");
    });
  };

  const onResend = () =>
    run(async () => {
      await resendConfirmationCode(email.trim());
      setNotice("A new code is on its way.");
    });

  const onForgot = (e) => {
    e.preventDefault();
    run(async () => {
      await forgotPassword(email.trim());
      switchMode("reset");
      setNotice(`If an account exists for ${email.trim()}, a reset code has been sent.`);
    });
  };

  const onReset = (e) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    run(async () => {
      await confirmForgotPassword({ email: email.trim(), code: code.trim(), newPassword: password });
      finishSignIn(await signIn(email.trim(), password));
    });
  };

  const onNewPassword = (e) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    run(async () => {
      finishSignIn(await completeNewPassword({ email: email.trim(), session: challengeSession, newPassword: password }));
    });
  };

  async function onHostedLogin() {
    run(() => startLogin({ returnTo }));
  }

  function onDevLogin() {
    setError("");
    try {
      loginWithDevToken();
    } catch (err) {
      setError(err.message || "Could not start a local dev session.");
    }
  }

  const emailField = (
    <Field label="Email">
      <input
        className="auth-input"
        type="email"
        autoComplete="email"
        placeholder="you@company.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        disabled={pending}
      />
    </Field>
  );

  const passwordField = (label, autoComplete) => (
    <Field label={label}>
      <input
        className="auth-input"
        type="password"
        autoComplete={autoComplete}
        placeholder="••••••••••••"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        minLength={8}
        disabled={pending}
      />
    </Field>
  );

  const confirmPasswordField = (
    <Field label="Confirm password">
      <input
        className="auth-input"
        type="password"
        autoComplete="new-password"
        placeholder="••••••••••••"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        required
        disabled={pending}
      />
    </Field>
  );

  const codeField = (
    <Field label="Verification code">
      <input
        className="auth-input auth-mono"
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder="123456"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
        disabled={pending}
        style={{ letterSpacing: "0.2em" }}
      />
    </Field>
  );

  let body;
  if (!nativeConfigured) {
    body = (
      <>
        {!hostedConfigured ? (
          <div className="auth-note">
            Cognito is not configured for this deployment. Missing{" "}
            <span className="auth-mono" style={{ color: "#ededed" }}>
              {[...missingAuthConfigKeys(), "VITE_COGNITO_REGION"].join(", ")}
            </span>
            .
          </div>
        ) : null}
        <button type="button" className="auth-btn" onClick={onHostedLogin} disabled={!hostedConfigured || pending}>
          {pending ? (
            <>
              <span className="auth-spinner" style={{ marginRight: 10 }} />
              Redirecting to Cognito
            </>
          ) : (
            "Continue with Cognito"
          )}
        </button>
      </>
    );
  } else if (mode === "signin") {
    body = (
      <form onSubmit={onSignIn} style={{ display: "grid", gap: 14 }}>
        {emailField}
        {passwordField("Password", "current-password")}
        <SubmitButton pending={pending} pendingLabel="Signing in">
          Sign in
        </SubmitButton>
        <div className="auth-row">
          <button type="button" className="auth-text-btn" onClick={() => switchMode("forgot")} disabled={pending}>
            Forgot password?
          </button>
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signup")} disabled={pending}>
            Create an account
          </button>
        </div>
      </form>
    );
  } else if (mode === "signup") {
    body = (
      <form onSubmit={onSignUp} style={{ display: "grid", gap: 14 }}>
        {emailField}
        {passwordField("Password", "new-password")}
        {confirmPasswordField}
        <SubmitButton pending={pending} pendingLabel="Creating account">
          Create account
        </SubmitButton>
        <div className="auth-row">
          <span style={{ fontSize: 12.5, color: "#6a6a6a" }}>Already have an account?</span>
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signin")} disabled={pending}>
            Sign in
          </button>
        </div>
      </form>
    );
  } else if (mode === "confirm") {
    body = (
      <form onSubmit={onConfirm} style={{ display: "grid", gap: 14 }}>
        {emailField}
        {codeField}
        <SubmitButton pending={pending} pendingLabel="Verifying">
          Verify email
        </SubmitButton>
        <div className="auth-row">
          <button type="button" className="auth-text-btn" onClick={onResend} disabled={pending || !email}>
            Resend code
          </button>
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signin")} disabled={pending}>
            Back to sign in
          </button>
        </div>
      </form>
    );
  } else if (mode === "forgot") {
    body = (
      <form onSubmit={onForgot} style={{ display: "grid", gap: 14 }}>
        {emailField}
        <SubmitButton pending={pending} pendingLabel="Sending code">
          Send reset code
        </SubmitButton>
        <div className="auth-row">
          <button type="button" className="auth-text-btn" onClick={() => switchMode("reset")} disabled={pending}>
            I already have a code
          </button>
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signin")} disabled={pending}>
            Back to sign in
          </button>
        </div>
      </form>
    );
  } else if (mode === "reset") {
    body = (
      <form onSubmit={onReset} style={{ display: "grid", gap: 14 }}>
        {emailField}
        {codeField}
        {passwordField("New password", "new-password")}
        {confirmPasswordField}
        <SubmitButton pending={pending} pendingLabel="Resetting">
          Reset password
        </SubmitButton>
        <div className="auth-row">
          <button type="button" className="auth-text-btn" onClick={() => switchMode("forgot")} disabled={pending}>
            Resend code
          </button>
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signin")} disabled={pending}>
            Back to sign in
          </button>
        </div>
      </form>
    );
  } else if (mode === "newpass") {
    body = (
      <form onSubmit={onNewPassword} style={{ display: "grid", gap: 14 }}>
        <div className="auth-note">
          Signed in as <span style={{ color: "#ededed" }}>{email}</span>
        </div>
        {passwordField("New password", "new-password")}
        {confirmPasswordField}
        <SubmitButton pending={pending} pendingLabel="Saving">
          Save and continue
        </SubmitButton>
        <div className="auth-row">
          <span />
          <button type="button" className="auth-text-btn" onClick={() => switchMode("signin")} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    );
  }

  const copy = COPY[nativeConfigured ? mode : "signin"];

  return (
    <AuthShell
      label={copy.label}
      title={copy.title}
      subtitle={copy.subtitle}
      footer={
        <p className="auth-mono" style={{ margin: 0, fontSize: 11, color: "#858585", letterSpacing: "0.06em" }}>
          SECURED BY AWS COGNITO
        </p>
      }
    >
      {error ? <div className="auth-note auth-note-bad">{error}</div> : null}
      {notice ? <div className="auth-note auth-note-good">{notice}</div> : null}

      {body}

      {devToken ? (
        <>
          <hr className="auth-divider" />
          <button type="button" className="auth-btn-ghost" onClick={onDevLogin}>
            Use local dev session
          </button>
        </>
      ) : null}
    </AuthShell>
  );
}
