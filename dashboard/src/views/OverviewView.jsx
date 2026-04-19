export default function OverviewView({ stats }) {
  const cards = [
    { label: "Total Transactions Today", value: stats.total, tone: "text-slate-100" },
    { label: "Blocked", value: stats.blocked, tone: "text-rose" },
    { label: "Pending Approval", value: stats.pending, tone: "text-amber" },
    { label: "Auto-Approved", value: stats.autoApproved, tone: "text-emerald" },
  ];

  return (
    <div className="animate-fadeIn p-6">
      <h1 className="mb-4 text-2xl font-semibold">Overview</h1>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="rounded-md border border-borderStrong bg-bgCard p-4">
            <div className="text-xs uppercase text-slate-400">{card.label}</div>
            <div className={`mt-2 font-mono text-2xl ${card.tone}`}>{card.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-6 rounded-md border border-dashed border-borderStrong bg-bgCard/70 p-10 text-center text-textMuted">
        Spend analytics coming soon
      </div>
    </div>
  );
}

