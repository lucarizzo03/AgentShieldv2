import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/overview", label: "Overview", icon: "⬡" },
  { to: "/activity", label: "Activity Feed", icon: "⊞" },
  { to: "/approvals", label: "Approvals", icon: "⚠", showPending: true },
  { to: "/register", label: "Register Agent", icon: "⊕" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="h-7 w-7 border border-amber bg-amber/10 [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
      <div className="font-mono text-sm tracking-wide text-slate-100">AgentShield</div>
    </div>
  );
}

export default function Sidebar({ pendingCount, activeAgentName = "my-booking-agent" }) {
  return (
    <aside className="fixed left-0 top-0 z-30 flex h-screen w-[220px] flex-col border-r border-borderStrong bg-bgSecondary/95 px-4 py-5 backdrop-blur">
      <BrandMark />
      <nav className="mt-8 flex flex-1 flex-col gap-1 text-sm">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `group flex items-center justify-between rounded-md border px-3 py-2 transition ${
                isActive
                  ? "border-amber/40 bg-amber/10 text-amber"
                  : "border-transparent text-slate-300 hover:border-borderStrong hover:bg-bgCard"
              }`
            }
          >
            <span className="flex items-center gap-2">
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </span>
            {item.showPending && pendingCount > 0 ? (
              <span className="rounded-full bg-amber px-2 py-0.5 text-[11px] font-semibold text-bgSecondary">
                {pendingCount}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>
      <div className="rounded-md border border-borderStrong bg-bgCard px-3 py-3 text-xs">
        <div className="mb-1 font-mono text-slate-100">{activeAgentName}</div>
        <div className="flex items-center gap-2 text-emerald">
          <span className="status-live-dot inline-block h-2 w-2 rounded-full bg-emerald" />
          <span>Active</span>
        </div>
      </div>
    </aside>
  );
}

