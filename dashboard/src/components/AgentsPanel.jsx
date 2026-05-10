import { useEffect, useState } from "react";

const shellCard = {
  border: "1px solid var(--border)",
  background: "linear-gradient(180deg, rgba(255,255,255,0.01) 0%, rgba(255,255,255,0) 100%), var(--bg-raised)",
  padding: 18,
  borderRadius: 8,
};

const inputStyle = {
  width: "100%",
  height: 38,
  background: "var(--bg)",
  border: "1px solid var(--border)",
  color: "var(--text-1)",
  borderRadius: 6,
  padding: "0 11px",
  fontSize: 13,
  fontFamily: "var(--font-mono)",
};

const subtleButton = {
  height: 32,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--text-2)",
  padding: "0 11px",
  borderRadius: 6,
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  cursor: "pointer",
};

const primaryButton = {
  height: 36,
  border: "1px solid var(--text-1)",
  background: "var(--text-1)",
  color: "var(--bg)",
  borderRadius: 6,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  fontWeight: 700,
  cursor: "pointer",
};

function Label({ children }) {
  return (
    <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.08em" }}>
      {children}
    </div>
  );
}

function Field({ label, hint, children, compact = false }) {
  return (
    <div style={{ marginBottom: compact ? 10 : 15 }}>
      <Label>{label}</Label>
      {hint ? <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 6, lineHeight: 1.35 }}>{hint}</div> : null}
      {children}
    </div>
  );
}

function Chip({ text, onRemove }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      style={{
        border: "1px solid var(--border-focus)",
        background: "var(--bg-overlay)",
        color: "var(--text-2)",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        padding: "5px 11px",
        cursor: "pointer",
      }}
    >
      {text} ×
    </button>
  );
}

function copy(value) {
  if (!value) return;
  navigator.clipboard.writeText(value).catch(() => {});
}

function SectionHeader({ title, subtitle, right }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
      <div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, color: "var(--text-1)", fontWeight: 600 }}>{title}</div>
        {subtitle ? <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4, lineHeight: 1.35 }}>{subtitle}</div> : null}
      </div>
      {right}
    </div>
  );
}

export default function AgentsPanel({
  agents,
  activeAgent,
  activeAgentId,
  activeHmac,
  form,
  onFormChange,
  showSuccess,
  showNewAgentForm,
  secretReveal,
  onToggleSecret,
  onShowNewAgent,
  onHideNewAgent,
  onCreateAgent,
  onAddBlockedVendor,
  onAddScope,
  onRemoveScope,
  onRunSafeTest,
  onRunSuspiciousTest,
  safeRunning,
  hitlRunning,
  onGoToActivity,
  onSaveScopes,
  scopesSaving,
  onSaveSettings,
  settingsSaving,
}) {
  const [scopeDraft, setScopeDraft] = useState("");
  const [scopeEditor, setScopeEditor] = useState([]);
  const [dirtyScopes, setDirtyScopes] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [settingsForm, setSettingsForm] = useState({
    name: "",
    daily: "0",
    perTx: "0",
    auto: "0",
    blocked: [],
    draftVendor: "",
    networks: ["base"],
    tokens: ["USDC"],
  });

  useEffect(() => {
    const next = activeAgent?.allowed_scopes || [];
    setScopeEditor(next);
    setDirtyScopes(false);
    setScopeDraft("");
  }, [activeAgent?.agent_id, activeAgent?.allowed_scopes]);

  useEffect(() => {
    if (!activeAgent) return;
    setSettingsForm({
      name: activeAgent.display_name || "",
      daily: String(activeAgent.daily_spend_limit_usd ?? 0),
      perTx: String(activeAgent.per_transaction_limit_usd ?? 0),
      auto: String(activeAgent.auto_approve_under_usd ?? 0),
      blocked: activeAgent.blocked_vendors || [],
      draftVendor: "",
      networks: activeAgent.allowed_networks?.length ? activeAgent.allowed_networks : ["base"],
      tokens: activeAgent.allowed_tokens?.length ? activeAgent.allowed_tokens : ["USDC"],
    });
    setSettingsDirty(false);
  }, [activeAgent]);

  const addEditorScope = () => {
    const value = scopeDraft.trim();
    if (!value) return;
    setScopeEditor((prev) => Array.from(new Set([...prev, value])));
    setScopeDraft("");
    setDirtyScopes(true);
  };

  const removeEditorScope = (scope) => {
    setScopeEditor((prev) => prev.filter((entry) => entry !== scope));
    setDirtyScopes(true);
  };

  const updateSettingsField = (key, value) => {
    setSettingsForm((prev) => ({ ...prev, [key]: value }));
    setSettingsDirty(true);
  };

  const addSettingsBlockedVendor = () => {
    const value = settingsForm.draftVendor.trim();
    if (!value) return;
    setSettingsForm((prev) => ({
      ...prev,
      blocked: Array.from(new Set([...prev.blocked, value])),
      draftVendor: "",
    }));
    setSettingsDirty(true);
  };

  const removeSettingsBlockedVendor = (vendor) => {
    setSettingsForm((prev) => ({ ...prev, blocked: prev.blocked.filter((entry) => entry !== vendor) }));
    setSettingsDirty(true);
  };

  const toggleSettingsNetwork = (network) => {
    setSettingsForm((prev) => ({
      ...prev,
      networks: prev.networks.includes(network)
        ? prev.networks.filter((entry) => entry !== network)
        : [...prev.networks, network],
    }));
    setSettingsDirty(true);
  };

  const toggleSettingsToken = (token) => {
    setSettingsForm((prev) => ({
      ...prev,
      tokens: prev.tokens.includes(token) ? prev.tokens.filter((entry) => entry !== token) : [...prev.tokens, token],
    }));
    setSettingsDirty(true);
  };

  const handleSaveSettings = async () => {
    const daily = Math.trunc(Number(settingsForm.daily));
    const perTx = Math.trunc(Number(settingsForm.perTx));
    const auto = Math.trunc(Number(settingsForm.auto));
    if (!settingsForm.name.trim()) return;
    if (![daily, perTx, auto].every((value) => Number.isFinite(value) && value >= 0)) return;
    await onSaveSettings({
      agent_name: settingsForm.name.trim(),
      daily_spend_limit_usd: daily,
      per_transaction_limit_usd: perTx,
      auto_approve_under_usd: auto,
      blocked_vendors: settingsForm.blocked,
      allowed_networks: settingsForm.networks,
      allowed_tokens: settingsForm.tokens,
      allowed_scopes: scopeEditor,
    });
    setSettingsDirty(false);
  };

  const hasAgent = Boolean(activeAgentId);
  const showCreateFlow = showNewAgentForm || !hasAgent;

  return (
    <div style={{ maxWidth: 980, display: "grid", gap: 14, gridTemplateColumns: "minmax(390px, 1fr) minmax(390px, 1fr)" }}>
      <div style={{ ...shellCard }}>
        <SectionHeader
          title="Agent Identity"
          subtitle="Credentials and scope policy for the selected agent."
          right={<button type="button" onClick={onShowNewAgent} style={subtleButton}>+ New Agent</button>}
        />

        {!hasAgent ? (
          <div style={{ border: "1px dashed var(--border)", borderRadius: 6, padding: 12, fontSize: 12, color: "var(--text-2)" }}>
            No active agent selected. Register one to enable Check 4 scope controls.
          </div>
        ) : (
          <>
            <Field label="agent_id" compact>
              <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", padding: "9px 10px", display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                <span>{activeAgentId}</span>
                <button type="button" onClick={() => copy(activeAgentId)} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>
                  [copy]
                </button>
              </div>
            </Field>

            <Field label="hmac_secret" compact>
              <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", padding: "9px 10px", display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                <span>{secretReveal ? activeHmac : "•••••••••••••••••••••••••••"}</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" onClick={() => copy(activeHmac)} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>
                    [copy]
                  </button>
                  <button type="button" onClick={onToggleSecret} style={{ border: "none", background: "transparent", color: "var(--text-2)", fontSize: 11, cursor: "pointer" }}>
                    [{secretReveal ? "hide" : "reveal"}]
                  </button>
                </div>
              </div>
            </Field>

            <div style={{ borderTop: "1px solid var(--border)", margin: "12px 0", opacity: 0.8 }} />

            <Field label="Goal Drift Scopes" hint="Check 4 will route out-of-scope goals and uncertain scope evaluations to HITL.">
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={scopeDraft}
                  onChange={(event) => setScopeDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addEditorScope();
                    }
                  }}
                  placeholder="travel booking"
                  style={{ ...inputStyle, flex: 1 }}
                />
                <button type="button" onClick={addEditorScope} style={{ ...subtleButton, height: 38, color: "var(--text-1)" }}>
                  Add
                </button>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
                {scopeEditor.length === 0 ? <span style={{ fontSize: 11, color: "var(--text-3)" }}>No scopes configured.</span> : null}
                {scopeEditor.map((scope) => (
                  <Chip key={scope} text={scope} onRemove={() => removeEditorScope(scope)} />
                ))}
              </div>
              <div style={{ marginTop: 11, display: "flex", justifyContent: "flex-start" }}>
                <button
                  type="button"
                  disabled={!dirtyScopes || scopesSaving}
                  onClick={() => onSaveScopes(scopeEditor)}
                  style={{
                    ...primaryButton,
                    minWidth: 132,
                    height: 34,
                    opacity: !dirtyScopes || scopesSaving ? 0.45 : 1,
                    cursor: !dirtyScopes || scopesSaving ? "not-allowed" : "pointer",
                  }}
                >
                  {scopesSaving ? "Saving..." : "Save Scopes"}
                </button>
              </div>
            </Field>
          </>
        )}
      </div>

      <div style={{ ...shellCard }}>
        <SectionHeader
          title={showCreateFlow ? "Register Agent" : "Agent Console"}
          subtitle="Create agents with policy defaults or run fast verification actions."
          right={
            hasAgent && showCreateFlow ? (
              <button type="button" onClick={onHideNewAgent} style={{ ...subtleButton, border: "none" }}>
                ← Back
              </button>
            ) : null
          }
        />

        {showCreateFlow ? (
          !showSuccess ? (
            <form onSubmit={onCreateAgent}>
              <Field label="Agent Name">
                <input
                  value={form.name}
                  placeholder="my-booking-agent"
                  onChange={(event) => onFormChange((prev) => ({ ...prev, name: event.target.value }))}
                  style={inputStyle}
                />
              </Field>

              <div style={{ display: "grid", gap: 10, gridTemplateColumns: "1fr 1fr" }}>
                <Field label="Daily Spend Limit (USD)">
                  <input type="number" min={0} step={1} value={form.daily} placeholder="500" onChange={(event) => onFormChange((prev) => ({ ...prev, daily: event.target.value }))} style={inputStyle} />
                </Field>
                <Field label="Per-Txn Limit (USD)">
                  <input type="number" min={0} step={1} value={form.perTx} placeholder="200" onChange={(event) => onFormChange((prev) => ({ ...prev, perTx: event.target.value }))} style={inputStyle} />
                </Field>
              </div>

              <Field label="Auto-Approve Under (USD)" hint="Above this amount will route to HITL.">
                <input type="number" min={0} step={1} value={form.auto} placeholder="25" onChange={(event) => onFormChange((prev) => ({ ...prev, auto: event.target.value }))} style={inputStyle} />
              </Field>

              <Field label="Goal Drift Scopes" hint="Add mission scopes now so Check 4 is active immediately.">
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={form.draftScope}
                    onChange={(event) => onFormChange((prev) => ({ ...prev, draftScope: event.target.value }))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        onAddScope();
                      }
                    }}
                    placeholder="travel booking"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <button type="button" onClick={onAddScope} style={{ ...subtleButton, height: 38, color: "var(--text-1)" }}>
                    Add
                  </button>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
                  {form.scopes.map((scope) => (
                    <Chip key={scope} text={scope} onRemove={() => onRemoveScope(scope)} />
                  ))}
                </div>
              </Field>

              <Field label="Asset Type">
                <div style={{ display: "flex", gap: 8 }}>
                  {["STABLECOIN", "FIAT"].map((asset) => (
                    <button
                      key={asset}
                      type="button"
                      onClick={() => onFormChange((prev) => ({ ...prev, asset }))}
                      style={{
                        ...subtleButton,
                        height: 32,
                        color: form.asset === asset ? "var(--text-1)" : "var(--text-2)",
                        background: form.asset === asset ? "var(--bg-overlay)" : "transparent",
                      }}
                    >
                      {asset}
                    </button>
                  ))}
                </div>
              </Field>

              {form.asset === "STABLECOIN" ? (
                <>
                  <Field label="Networks">
                    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12, color: "var(--text-2)" }}>
                      {["ethereum", "base", "solana", "polygon", "arbitrum"].map((network) => (
                        <label key={network} style={{ display: "inline-flex", gap: 6, alignItems: "center", textTransform: "lowercase" }}>
                          <input
                            type="checkbox"
                            checked={form.networks.includes(network)}
                            onChange={() => onFormChange((prev) => ({ ...prev, networks: prev.networks.includes(network) ? prev.networks.filter((value) => value !== network) : [...prev.networks, network] }))}
                          />
                          {network}
                        </label>
                      ))}
                    </div>
                  </Field>
                  <Field label="Tokens">
                    <div style={{ display: "flex", gap: 8 }}>
                      {["USDC", "USDT"].map((token) => (
                        <button
                          key={token}
                          type="button"
                          onClick={() => onFormChange((prev) => ({ ...prev, tokens: prev.tokens.includes(token) ? prev.tokens.filter((value) => value !== token) : [...prev.tokens, token] }))}
                          style={{
                            ...subtleButton,
                            height: 30,
                            color: form.tokens.includes(token) ? "var(--text-1)" : "var(--text-2)",
                            background: form.tokens.includes(token) ? "var(--bg-overlay)" : "transparent",
                          }}
                        >
                          {token}
                        </button>
                      ))}
                    </div>
                  </Field>
                </>
              ) : null}

              <Field label="Blocked Vendors">
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={form.draftVendor}
                    onChange={(event) => onFormChange((prev) => ({ ...prev, draftVendor: event.target.value }))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        onAddBlockedVendor();
                      }
                    }}
                    placeholder="badvendor.example"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <button type="button" onClick={onAddBlockedVendor} style={{ ...subtleButton, height: 38, color: "var(--text-1)" }}>
                    Add
                  </button>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
                  {form.blocked.map((vendor) => (
                    <Chip
                      key={vendor}
                      text={vendor}
                      onRemove={() => onFormChange((prev) => ({ ...prev, blocked: prev.blocked.filter((entry) => entry !== vendor) }))}
                    />
                  ))}
                </div>
              </Field>

              <button type="submit" style={{ ...primaryButton, width: "100%" }}>
                Create Agent
              </button>
            </form>
          ) : (
            <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", padding: 14 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--green)", marginBottom: 6 }}>Agent created successfully.</div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>Credentials are available in the identity panel.</div>
              <button type="button" onClick={onGoToActivity} style={{ ...subtleButton, color: "var(--text-1)" }}>
                Open Activity
              </button>
            </div>
          )
        ) : (
          <>
            <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", padding: 14, marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>Current Agent Settings</div>

              <Field label="Agent Name" compact>
                <input value={settingsForm.name} onChange={(event) => updateSettingsField("name", event.target.value)} style={inputStyle} />
              </Field>

              <div style={{ display: "grid", gap: 10, gridTemplateColumns: "1fr 1fr" }}>
                <Field label="Daily Spend Limit (USD)" compact>
                  <input type="number" min={0} step={1} value={settingsForm.daily} onChange={(event) => updateSettingsField("daily", event.target.value)} style={inputStyle} />
                </Field>
                <Field label="Per-Txn Limit (USD)" compact>
                  <input type="number" min={0} step={1} value={settingsForm.perTx} onChange={(event) => updateSettingsField("perTx", event.target.value)} style={inputStyle} />
                </Field>
              </div>

              <Field label="Auto-Approve Under (USD)" compact>
                <input type="number" min={0} step={1} value={settingsForm.auto} onChange={(event) => updateSettingsField("auto", event.target.value)} style={inputStyle} />
              </Field>

              <Field label="Allowed Networks" compact>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {["ethereum", "base", "solana", "polygon", "arbitrum"].map((network) => (
                    <button
                      key={network}
                      type="button"
                      onClick={() => toggleSettingsNetwork(network)}
                      style={{
                        ...subtleButton,
                        height: 30,
                        color: settingsForm.networks.includes(network) ? "var(--text-1)" : "var(--text-2)",
                        background: settingsForm.networks.includes(network) ? "var(--bg-overlay)" : "transparent",
                      }}
                    >
                      {network}
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="Allowed Tokens" compact>
                <div style={{ display: "flex", gap: 8 }}>
                  {["USDC", "USDT"].map((token) => (
                    <button
                      key={token}
                      type="button"
                      onClick={() => toggleSettingsToken(token)}
                      style={{
                        ...subtleButton,
                        height: 30,
                        color: settingsForm.tokens.includes(token) ? "var(--text-1)" : "var(--text-2)",
                        background: settingsForm.tokens.includes(token) ? "var(--bg-overlay)" : "transparent",
                      }}
                    >
                      {token}
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="Blocked Vendors" compact>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={settingsForm.draftVendor}
                    onChange={(event) => updateSettingsField("draftVendor", event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addSettingsBlockedVendor();
                      }
                    }}
                    placeholder="badvendor.example"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <button type="button" onClick={addSettingsBlockedVendor} style={{ ...subtleButton, height: 38, color: "var(--text-1)" }}>
                    Add
                  </button>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
                  {settingsForm.blocked.map((vendor) => (
                    <Chip key={vendor} text={vendor} onRemove={() => removeSettingsBlockedVendor(vendor)} />
                  ))}
                </div>
              </Field>

              <button
                type="button"
                onClick={handleSaveSettings}
                disabled={!settingsDirty || settingsSaving}
                style={{
                  ...primaryButton,
                  width: "100%",
                  opacity: !settingsDirty || settingsSaving ? 0.45 : 1,
                  cursor: !settingsDirty || settingsSaving ? "not-allowed" : "pointer",
                }}
              >
                {settingsSaving ? "Saving..." : "Save Agent Settings"}
              </button>
            </div>

            <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", padding: 14 }}>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>Developer verification tools</div>
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <button
                  type="button"
                  onClick={onRunSafeTest}
                  disabled={safeRunning}
                  style={{
                    ...subtleButton,
                    border: `1px solid ${safeRunning ? "var(--border)" : "var(--green)"}`,
                    color: safeRunning ? "var(--text-3)" : "var(--green)",
                    background: safeRunning ? "transparent" : "rgba(0,200,83,0.12)",
                    cursor: safeRunning ? "not-allowed" : "pointer",
                  }}
                >
                  {safeRunning ? "running..." : "Run SAFE Test"}
                </button>
                <button
                  type="button"
                  onClick={onRunSuspiciousTest}
                  disabled={hitlRunning}
                  style={{
                    ...subtleButton,
                    border: `1px solid ${hitlRunning ? "var(--border)" : "var(--amber)"}`,
                    color: hitlRunning ? "var(--text-3)" : "var(--amber)",
                    background: hitlRunning ? "transparent" : "rgba(255,149,0,0.12)",
                    cursor: hitlRunning ? "not-allowed" : "pointer",
                  }}
                >
                  {hitlRunning ? "running..." : "Run HITL Test"}
                </button>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>active_agent: {activeAgentId}</div>
            </div>
          </>
        )}
      </div>

      <div style={{ gridColumn: "1 / -1", fontSize: 12, color: "var(--text-3)", borderTop: "1px solid var(--border)", paddingTop: 10 }}>
        Agents: {agents.length} total · Check 4 scope controls and dashboard counts are aligned to today (UTC).
      </div>
    </div>
  );
}
