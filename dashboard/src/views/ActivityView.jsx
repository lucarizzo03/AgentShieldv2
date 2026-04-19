import { useEffect, useMemo, useState } from "react";

const statusTheme = {
  SAFE: "bg-emerald/20 text-emerald border border-emerald/40",
  PENDING: "bg-amber/20 text-amber border border-amber/50 animate-pulse",
  BLOCKED: "bg-rose/20 text-rose border border-rose/50",
  APPROVED: "text-emerald border border-emerald/50",
  DENIED: "text-rose border border-rose/50",
};

const statusIcon = {
  SAFE: "✓",
  PENDING: "⚠",
  BLOCKED: "✕",
  APPROVED: "◷",
  DENIED: "✕",
};

const filters = ["ALL", "SAFE", "SUSPICIOUS", "MALICIOUS", "PENDING"];

function derivesFilterType(row) {
  if (row.status === "PENDING") return "PENDING";
  if (row.status === "BLOCKED" || row.status === "DENIED") return "MALICIOUS";
  if (row.status === "APPROVED") return "SUSPICIOUS";
  return "SAFE";
}

export default function ActivityView({ rows, onResolvePending, agents = [], activeAgentId, onAgentChange }) {
  const [activeFilter, setActiveFilter] = useState("ALL");
  const [expanded, setExpanded] = useState(null);
  const [liveRows, setLiveRows] = useState(rows);

  useEffect(() => {
    setLiveRows(rows.map((row) => ({ ...row, pulse: row.pulse ?? false })));
  }, [rows]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLiveRows((current) => {
        const newRow = {
          id: `tx_live_${Date.now()}`,
          time: "10:45:12",
          status: "SAFE",
          vendor: "Delta Airlines",
          amount: "$22.00 USDC",
          network: "base",
          goal: "Book flight NYC→LAX Aug 1",
          reason: "Budget and intent checks passed",
          details: {
            a: "✓ budget ok  ✓ no loop",
            b: "✓ vendor ok  ✓ amount ok",
            c: 'alignment: 0.91 — SAFE, reason: "goal and action aligned"',
          },
          pulse: true,
        };
        return [newRow, ...current];
      });
      setTimeout(() => {
        setLiveRows((current) => current.map((row) => ({ ...row, pulse: false })));
      }, 1500);
    }, 4500);
    return () => clearTimeout(timer);
  }, []);

  const filteredRows = useMemo(() => {
    if (activeFilter === "ALL") return liveRows;
    return liveRows.filter((row) => derivesFilterType(row) === activeFilter);
  }, [activeFilter, liveRows]);

  return (
    <div className="animate-fadeIn space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-borderStrong bg-bgCard px-4 py-3">
        <h1 className="text-xl font-semibold">Activity Feed</h1>
        <div className="flex items-center gap-3">
          <select
            className="rounded border border-borderStrong bg-bgSecondary px-3 py-2 text-sm"
            value={activeAgentId}
            onChange={(e) => onAgentChange?.(e.target.value)}
          >
            {agents.map((agent) => (
              <option key={agent.agent_id} value={agent.agent_id}>
                {agent.display_name}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-2 text-sm text-emerald">
            <span className="status-live-dot inline-block h-2 w-2 rounded-full bg-emerald" />
            Live
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {filters.map((filter) => (
          <button
            key={filter}
            type="button"
            onClick={() => setActiveFilter(filter)}
            className={`rounded-full border px-3 py-1 text-xs ${
              activeFilter === filter
                ? "border-amber bg-amber/20 text-amber"
                : "border-borderStrong text-slate-300"
            }`}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {filteredRows.map((row, index) => (
          <div
            key={row.id}
            className={`animate-rowSlide rounded-md border border-borderStrong bg-bgCard p-4 transition ${
              row.pulse ? "animate-glowPulse" : ""
            }`}
            style={{ animationDelay: `${index * 55}ms` }}
          >
            <div className="grid grid-cols-12 items-center gap-3 text-sm">
              <div className="col-span-2 font-mono text-xs text-textMuted">{row.time}</div>
              <div className="col-span-2">
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs ${statusTheme[row.status]}`}>
                  <span>{statusIcon[row.status]}</span>
                  {row.status}
                </span>
              </div>
              <div className="col-span-2 font-semibold">{row.vendor}</div>
              <div className="col-span-2 text-right font-mono">{row.amount}</div>
              <div className="col-span-1">
                <span className="rounded border border-borderStrong bg-bgSecondary px-2 py-1 text-[11px] capitalize text-slate-300">
                  {row.network}
                </span>
              </div>
              <div className="col-span-2 truncate italic text-textMuted">{row.goal}</div>
              <div className="col-span-1 text-[11px] text-textMuted">{row.reason}</div>
            </div>

            <div className="mt-3 flex justify-end gap-2">
              {row.status === "PENDING" ? (
                <>
                  <button
                    type="button"
                    className="rounded bg-amber px-3 py-1 text-xs font-semibold text-bgSecondary"
                    onClick={() => onResolvePending(row.id, "APPROVED")}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="rounded border border-rose px-3 py-1 text-xs font-semibold text-rose"
                    onClick={() => onResolvePending(row.id, "DENIED")}
                  >
                    Deny
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="rounded border border-borderStrong px-3 py-1 text-xs hover:border-amber"
                  onClick={() => setExpanded((prev) => (prev === row.id ? null : row.id))}
                >
                  View
                </button>
              )}
            </div>

            {expanded === row.id ? (
              <div className="mt-3 rounded border border-borderStrong bg-bgSecondary p-3 font-mono text-xs text-slate-300">
                <div>Check A (Redis): {row.details.a}</div>
                <div className="mt-1">Check B (Policy): {row.details.b}</div>
                <div className="mt-1">Check C (SLM): {row.details.c}</div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

