import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  BarChart3, BookOpen, Bot, Database, FileText, GitCompare, LayoutDashboard, LogOut, Menu, Moon, Settings, Sun,
  Table2, Terminal, X, type LucideIcon,
} from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { useActiveDataset } from "../hooks/useDataset";
import { useTheme } from "../hooks/useTheme";
import { SampleBadge } from "./ui";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#16294F" />
        <path d="M8.5 7v6.5a2.7 2.7 0 0 0 2 2.6V25" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M10.5 7v5M12.5 7v6.5a2.7 2.7 0 0 1-2 2.6" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <rect x="16.5" y="17" width="3" height="8" rx="1" fill="#FF6B57" />
        <rect x="21" y="12" width="3" height="13" rx="1" fill="#FF6B57" />
        <rect x="25.5" y="8" width="3" height="17" rx="1" fill="#FF8A79" />
      </svg>
      {!compact && <span className="text-[15px] font-semibold tracking-tight text-white">Restaurant<span className="text-[#FF8A79]">IQ</span></span>}
    </span>
  );
}

const NAV: { group: string; items: { to: string; label: string; icon: LucideIcon }[] }[] = [
  { group: "Overview", items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard }] },
  { group: "Analyze", items: [
    { to: "/explorer", label: "Explorer", icon: Table2 },
    { to: "/market", label: "Market Analysis", icon: BarChart3 },
    { to: "/compare", label: "Compare", icon: GitCompare },
  ] },
  { group: "Tools", items: [
    { to: "/sql", label: "SQL Playground", icon: Terminal },
    { to: "/analyst", label: "AI Analyst", icon: Bot },
  ] },
  { group: "Deliver", items: [{ to: "/reports", label: "Reports", icon: FileText }] },
  { group: "Data & Settings", items: [
    { to: "/data", label: "Data", icon: Database },
    { to: "/methodology", label: "Methodology", icon: BookOpen },
    { to: "/settings", label: "Settings", icon: Settings },
  ] },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <Link to="/" className="flex h-16 items-center px-5" onClick={onNavigate} aria-label="RestaurantIQ home"><Logo /></Link>
      <nav className="flex-1 overflow-y-auto px-3 pb-6" aria-label="Main navigation">
        {NAV.map((g) => (
          <div key={g.group} className="mt-5 first:mt-2">
            <p className="px-3 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-sidebar-ink/60">{g.group}</p>
            <ul className="space-y-0.5">
              {g.items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.to === "/"} onClick={onNavigate}
                           className={({ isActive }) => `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                             isActive ? "bg-sidebar-hover font-medium text-white" : "text-sidebar-ink hover:bg-sidebar-hover hover:text-white"}`}>
                    {({ isActive }) => (
                      <>
                        {isActive && <span className="absolute left-0 top-1.5 h-[calc(100%-12px)] w-[3px] rounded-r bg-accent" aria-hidden />}
                        <item.icon className={`h-4 w-4 shrink-0 ${isActive ? "text-accent" : ""}`} strokeWidth={1.75} aria-hidden />
                        {item.label}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <p className="px-5 pb-5 text-2xs leading-relaxed text-sidebar-ink/60">Turn Restaurant Data Into Smarter Business Decisions.</p>
    </div>
  );
}

/** Header user menu: who is signed in, Settings and Sign out. */
function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  if (!user) return null;
  const initials = user.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "U";
  const signOut = async () => {
    setBusy(true);
    try { await logout(); } finally { setBusy(false); }
  };
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
              aria-label={`Account menu for ${user.name}`}
              className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm text-ink transition hover:bg-surface-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink" aria-hidden>{initials}</span>
        <span className="hidden max-w-[10rem] truncate font-medium sm:inline">{user.name}</span>
      </button>
      {open && (
        <div role="menu" aria-label="Account" className="card absolute right-0 z-40 mt-1 w-60 p-1 shadow-pop">
          <div className="border-b border-line px-3 py-2">
            <p className="truncate text-sm font-semibold text-ink">{user.name}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
            {user.is_demo && <p className="mt-1 text-2xs font-semibold uppercase tracking-wide text-warning">Demo account</p>}
          </div>
          <Link role="menuitem" to="/settings" onClick={() => setOpen(false)}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted hover:bg-surface-3 hover:text-ink">
            <Settings className="h-4 w-4" aria-hidden /> Settings
          </Link>
          <button role="menuitem" type="button" onClick={signOut} disabled={busy}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-muted hover:bg-surface-3 hover:text-ink disabled:opacity-50">
            <LogOut className="h-4 w-4" aria-hidden /> {busy ? "Signing out..." : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" onClick={toggle} className="btn-ghost p-2" aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
    </button>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const active = useActiveDataset();
  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);
  const ds = active.data;

  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-pop">Skip to content</a>
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 bg-sidebar lg:block">
        <SidebarContent />
      </aside>
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-sidebar shadow-pop">
            <button className="absolute right-3 top-4 rounded-lg p-2 text-sidebar-ink hover:bg-sidebar-hover" onClick={() => setDrawer(false)} aria-label="Close navigation">
              <X className="h-4 w-4" />
            </button>
            <SidebarContent onNavigate={() => setDrawer(false)} />
          </aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/90 px-4 backdrop-blur sm:px-6">
          <button className="btn-ghost -ml-2 p-2 lg:hidden" onClick={() => setDrawer(true)} aria-label="Open navigation" aria-expanded={drawer}>
            <Menu className="h-5 w-5" />
          </button>
          <span className="lg:hidden"><Logo compact /></span>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {ds ? (
              <Link to="/data" className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1 text-sm hover:bg-surface-3" title="Active dataset version">
                <Database className="h-4 w-4 shrink-0 text-subtle" aria-hidden />
                <span className="truncate font-medium text-ink">{ds.name}</span>
                <span className="shrink-0 rounded bg-surface-3 px-1.5 text-xs font-semibold text-muted">{ds.dataset_id}</span>
              </Link>
            ) : (
              !active.isLoading && <Link to="/data" className="text-sm text-muted hover:text-ink">No dataset loaded</Link>
            )}
            {ds?.is_demo && <span className="hidden md:inline-flex"><SampleBadge /></span>}
          </div>
          <ThemeToggle />
          <UserMenu />
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
