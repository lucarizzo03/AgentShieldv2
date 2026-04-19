import { useEffect, useMemo, useState } from "react";

function formatElapsed(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs.toString().padStart(2, "0")}s`;
}

function Timer({ createdAtEpoch }) {
  const [elapsed, setElapsed] = useState(() => Math.max(0, Math.floor(Date.now() / 1000 - createdAtEpoch)));
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - createdAtEpoch)));
    }, 1000);
    return () => clearInterval(timer);
  }, [createdAtEpoch]);

  const style =
    elapsed >= 300
      ? "text-rose animate-pulse"
      : elapsed >= 180
      ? "text-amber"
      : "text-slate-400";

  return <span className={`font-mono text-xs ${style}`}>◷ {formatElapsed(elapsed)} ago</span>;
}

function RiskItem({ label, children }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">◉ {label}</div>
      <div className="space-y-1 text-sm text-slate-200">{children}</div>
    </div>
  );
}

export default function ApprovalsView({ cards, onDecision }) {
  const [notes, setNotes] = useState({});
  const pending = useMemo(() => cards, [cards]);
  const openCount = useMemo(() => cards.filter((card) => !card.closing).length, [cards]);

  return (
    <div className="animate-fadeIn p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Pending Approvals</h1>
          <p className="mt-1 text-sm text-textMuted">
            Review flagged transactions before funds are released
          </p>
        </div>
          <span className="rounded-full border border-amber/50 bg-amber/10 px-3 py-1 text-xs text-amber">
          {openCount} pending
        </span>
      </div>

      {pending.length === 0 ? (
        <div className="mt-20 text-center">
          <div className="mx-auto mb-3 h-10 w-10 border border-emerald bg-emerald/10 [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
          <h2 className="text-lg font-semibold text-emerald">All clear — no pending approvals</h2>
          <p className="text-sm text-textMuted">Your agents are operating within policy</p>
        </div>
      ) : (
        <div className="space-y-4">
          {pending.map((card) => (
            <div
              key={card.id}
              className={`rounded-xl border bg-bgCard p-5 transition ${
                card.flash === "approve"
                  ? "border-emerald/50 bg-emerald/5"
                  : card.flash === "deny"
                  ? "border-rose/50 bg-rose/5"
                  : "border-borderStrong"
              } ${card.closing ? "scale-[0.99] opacity-40" : "opacity-100"}`}
            >
              <div className="mb-4 flex items-center justify-between border-b border-borderStrong pb-3">
                <span className="text-sm font-semibold text-amber">⚠ APPROVAL REQUIRED</span>
                <Timer createdAtEpoch={card.createdAtEpoch} />
              </div>

              <div className="space-y-4">
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-400">AGENT GOAL</div>
                  <p className="text-sm text-slate-100">{card.goal}</p>
                </div>
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-400">ATTEMPTED ACTION</div>
                  <p className="text-sm">{card.action}</p>
                  <p className="mt-1 text-xs text-textMuted">{card.meta}</p>
                </div>

                <div className="border-t border-borderStrong pt-3">
                  <div className="mb-2 text-xs uppercase text-slate-400">RISK SIGNALS</div>
                  <RiskItem label={`SLM Alignment Score: ${card.slmScore} — ${card.slmLabel}`}>
                    <p>{card.slmReason}</p>
                  </RiskItem>
                  <RiskItem label="Redis Check A">
                    {card.redis.map((line) => (
                      <p key={line}>• {line}</p>
                    ))}
                  </RiskItem>
                  <RiskItem label="Policy Check B">
                    {card.policy.map((line) => (
                      <p key={line}>• {line}</p>
                    ))}
                  </RiskItem>
                </div>

                <div className="space-y-2">
                  <label className="text-xs text-slate-400">Note (optional):</label>
                  <input
                    value={notes[card.id] || ""}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [card.id]: e.target.value }))}
                    className="w-full rounded border border-borderStrong bg-bgSecondary px-3 py-2 text-sm outline-none focus:border-amber"
                  />
                </div>

                <div className="flex gap-3">
                  <button
                    type="button"
                    className="rounded bg-emerald px-4 py-2 text-sm font-semibold text-bgSecondary"
                    disabled={card.closing}
                    onClick={() => onDecision(card.id, "APPROVE", notes[card.id] || "")}
                  >
                    ✓ APPROVE TRANSACTION
                  </button>
                  <button
                    type="button"
                    className="rounded border border-rose px-4 py-2 text-sm font-semibold text-rose"
                    disabled={card.closing}
                    onClick={() => onDecision(card.id, "DENY", notes[card.id] || "")}
                  >
                    ✕ DENY
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

