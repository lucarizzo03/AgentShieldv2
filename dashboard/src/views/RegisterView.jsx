import { useMemo, useState } from "react";

const networks = ["ethereum", "base", "solana", "polygon", "arbitrum"];
const tokens = ["USDC", "USDT"];

function randomCredential(prefix) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let value = "";
  for (let i = 0; i < 16; i += 1) value += chars[Math.floor(Math.random() * chars.length)];
  return `${prefix}_${value}`;
}

function CodeSnippet({ credentials }) {
  const snippet = `POST https://api.agentshield.com/v1/spend-request
Headers:
  x-agent-id: ${credentials.agentId}
  x-timestamp: <ISO8601>
  x-signature: <HMAC-SHA256>
`;
  return (
    <div className="relative mt-4 rounded-md border border-borderStrong bg-bgSecondary p-4 font-mono text-xs text-slate-200">
      <button
        type="button"
        className="absolute right-3 top-3 rounded border border-borderStrong px-2 py-1 text-[10px] hover:border-amber hover:text-amber"
        onClick={() => navigator.clipboard.writeText(snippet)}
      >
        Copy
      </button>
      <pre className="overflow-x-auto whitespace-pre-wrap">{snippet}</pre>
    </div>
  );
}

export default function RegisterView({ onCreateAgent, onGoDashboard }) {
  const [form, setForm] = useState({
    agentName: "",
    dailyLimit: "",
    perTxnLimit: "",
    autoApproveUnder: "",
    blockedVendors: [],
    assetType: "STABLECOIN",
    allowedNetworks: ["base"],
    allowedTokens: ["USDC"],
  });
  const [tagDraft, setTagDraft] = useState("");
  const [created, setCreated] = useState(null);
  const [revealSecret, setRevealSecret] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = useMemo(
    () =>
      form.agentName &&
      form.dailyLimit &&
      form.perTxnLimit &&
      form.autoApproveUnder &&
      form.blockedVendors.length > 0,
    [form]
  );

  const updateField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const addTag = () => {
    const value = tagDraft.trim();
    if (!value || form.blockedVendors.includes(value)) return;
    updateField("blockedVendors", [...form.blockedVendors, value]);
    setTagDraft("");
  };

  const toggleCollectionItem = (key, item) => {
    const values = form[key];
    const next = values.includes(item) ? values.filter((x) => x !== item) : [...values, item];
    updateField(key, next);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      const createdAgent = await onCreateAgent(form);
      setCreated({
        agentId: createdAgent.agent_id || randomCredential("agt"),
        hmacSecret: createdAgent.hmac_secret || randomCredential("sk_live"),
      });
    } catch (err) {
      setError(err.message || "Failed to create agent");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="card-glow w-full max-w-[560px] rounded-xl border border-borderStrong bg-bgCard/95 p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex w-fit items-center gap-3">
            <div className="h-7 w-7 border border-amber bg-amber/10 [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
            <div className="font-mono text-lg tracking-wide">AgentShield</div>
          </div>
          <p className="text-sm text-textMuted">Spending firewall for autonomous agents</p>
        </div>

        {!created ? (
          <form className="space-y-4" onSubmit={submit}>
            <label className="block space-y-1 text-sm">
              <span>Agent Name</span>
              <input
                className="w-full rounded-md border border-borderStrong bg-bgSecondary px-3 py-2 outline-none focus:border-amber"
                placeholder="my-booking-agent"
                value={form.agentName}
                onChange={(e) => updateField("agentName", e.target.value)}
              />
            </label>

            {[
              ["dailyLimit", "Daily Spend Limit", "500"],
              ["perTxnLimit", "Per-Transaction Limit", "100"],
              ["autoApproveUnder", "Auto-Approve Under", "25"],
            ].map(([key, label, placeholder]) => (
              <label key={key} className="block space-y-1 text-sm">
                <span>{label}</span>
                <div className="flex items-center rounded-md border border-borderStrong bg-bgSecondary px-3">
                  <span className="font-mono text-textMuted">$</span>
                  <input
                    type="number"
                    className="w-full bg-transparent px-2 py-2 outline-none"
                    placeholder={placeholder}
                    value={form[key]}
                    onChange={(e) => updateField(key, e.target.value)}
                  />
                </div>
              </label>
            ))}

            <div className="space-y-2 text-sm">
              <span>Blocked Vendors</span>
              <input
                className="w-full rounded-md border border-borderStrong bg-bgSecondary px-3 py-2 outline-none focus:border-amber"
                placeholder="type vendor and hit enter"
                value={tagDraft}
                onChange={(e) => setTagDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTag();
                  }
                }}
              />
              <div className="flex flex-wrap gap-2">
                {form.blockedVendors.map((vendor) => (
                  <button
                    key={vendor}
                    type="button"
                    onClick={() =>
                      updateField(
                        "blockedVendors",
                        form.blockedVendors.filter((v) => v !== vendor)
                      )
                    }
                    className="rounded-full border border-amber/40 bg-amber/10 px-2 py-1 text-xs text-amber"
                  >
                    {vendor} ×
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2 text-sm">
              <span>Asset Type</span>
              <div className="grid grid-cols-2 gap-2 rounded-md border border-borderStrong bg-bgSecondary p-1">
                {["STABLECOIN", "FIAT"].map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => updateField("assetType", type)}
                    className={`rounded px-2 py-2 text-xs font-semibold ${
                      form.assetType === type ? "bg-amber text-bgSecondary" : "text-slate-300"
                    }`}
                  >
                    {type}
                  </button>
                ))}
              </div>
            </div>

            {form.assetType === "STABLECOIN" ? (
              <div className="space-y-4 rounded-md border border-borderStrong bg-bgSecondary p-3">
                <div className="space-y-2 text-sm">
                  <span>Allowed Networks</span>
                  <div className="grid grid-cols-2 gap-2">
                    {networks.map((network) => (
                      <label key={network} className="flex items-center gap-2 text-xs capitalize">
                        <input
                          type="checkbox"
                          checked={form.allowedNetworks.includes(network)}
                          onChange={() => toggleCollectionItem("allowedNetworks", network)}
                        />
                        <span>{network}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="space-y-2 text-sm">
                  <span>Allowed Tokens</span>
                  <div className="flex gap-2">
                    {tokens.map((token) => (
                      <button
                        key={token}
                        type="button"
                        onClick={() => toggleCollectionItem("allowedTokens", token)}
                        className={`rounded-full border px-3 py-1 text-xs ${
                          form.allowedTokens.includes(token)
                            ? "border-amber bg-amber/20 text-amber"
                            : "border-borderStrong text-slate-300"
                        }`}
                      >
                        {token}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}

            <button
              type="submit"
              className={`mt-2 w-full rounded-md py-3 font-semibold ${
                canSubmit && !submitting
                  ? "bg-amber text-bgSecondary"
                  : "cursor-not-allowed bg-amber/30 text-slate-700"
              }`}
              disabled={!canSubmit || submitting}
            >
              {submitting ? "Creating..." : "Create Agent →"}
            </button>
            {error ? <p className="text-sm text-rose">{error}</p> : null}
          </form>
        ) : (
          <div className="space-y-4 rounded-md border border-emerald/40 bg-emerald/5 p-4">
            <div className="font-semibold text-emerald">✓ Agent created successfully</div>
            <div className="space-y-3 rounded-md border border-borderStrong bg-bgSecondary p-3 text-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="mb-1 text-xs uppercase text-textMuted">agent_id</div>
                  <div className="font-mono">{created.agentId}</div>
                </div>
                <button
                  type="button"
                  className="rounded border border-borderStrong px-2 py-1 text-xs hover:border-amber"
                  onClick={() => navigator.clipboard.writeText(created.agentId)}
                >
                  Copy
                </button>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="mb-1 text-xs uppercase text-textMuted">hmac_secret</div>
                  <div className="font-mono">
                    {revealSecret ? created.hmacSecret : `${created.hmacSecret.slice(0, 10)}...`}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="rounded border border-borderStrong px-2 py-1 text-xs hover:border-amber"
                    onClick={() => navigator.clipboard.writeText(created.hmacSecret)}
                  >
                    Copy
                  </button>
                  <button
                    type="button"
                    className="rounded border border-borderStrong px-2 py-1 text-xs hover:border-amber"
                    onClick={() => setRevealSecret((prev) => !prev)}
                  >
                    {revealSecret ? "Hide" : "Reveal"}
                  </button>
                </div>
              </div>
            </div>
            <CodeSnippet credentials={created} />
            <div className="flex gap-2">
              <button type="button" className="rounded border border-borderStrong px-3 py-2 text-sm hover:border-amber">
                View Integration Docs
              </button>
              <button
                type="button"
                className="rounded bg-amber px-3 py-2 text-sm font-semibold text-bgSecondary"
                onClick={onGoDashboard}
              >
                Go to Dashboard →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

