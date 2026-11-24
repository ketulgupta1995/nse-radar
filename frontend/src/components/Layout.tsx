import { PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { NAV_GROUPS, routes } from "@/routes";
import { useTheme } from "@/lib/theme";
import type { ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import AlertBadge from "./AlertBadge";
import { Toaster } from "@/components/ui/toaster";
import CommandPalette from "./CommandPalette";
import StatusIndicator from "./StatusIndicator";

const KEY = "sidebar-collapsed";
const THEMES: ThemeChoice[] = ["dark", "light", "system"];

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export default function Layout() {
  const { theme, setTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = () => {
    const next = !collapsed;
    try {
      localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
    setCollapsed(next);
  };
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const nav = routes.filter((r) => r.nav);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside
        className={cn(
          "sticky top-0 flex h-screen flex-none flex-col gap-3 overflow-y-auto border-r border-border bg-card p-3",
          collapsed ? "w-[60px] items-center" : "w-[220px]",
        )}
      >
        <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-between px-1")}>
          {!collapsed && <span className="text-base font-bold">stock-tools</span>}
          <button
            type="button"
            onClick={toggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="cursor-pointer rounded-control border-0 bg-transparent p-1 text-muted-foreground hover:bg-muted"
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        <button
          type="button"
          onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
          aria-label="Search stocks and pages"
          title="Search (Ctrl+K)"
          className={cn(
            "flex cursor-pointer items-center gap-2 rounded-control border border-border bg-background p-2 text-sm text-muted-foreground hover:text-foreground",
            collapsed && "justify-center",
          )}
        >
          <Search size={16} />
          {!collapsed && (
            <>
              <span className="flex-1 text-left">Search…</span>
              <kbd className="font-mono text-xs">Ctrl K</kbd>
            </>
          )}
        </button>

        <nav className="flex flex-col gap-3" aria-label="Main">
          {NAV_GROUPS.map((g) => {
            const items = nav.filter((r) => r.group === g);
            if (items.length === 0) return null;
            return (
              <div key={g} className="flex flex-col gap-0.5">
                {!collapsed && (
                  <div className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{g}</div>
                )}
                {items.map((r) => (
                  <NavLink
                    key={r.path}
                    to={r.path}
                    end={r.path === "/"}
                    title={collapsed ? r.label : undefined}
                    aria-label={collapsed ? r.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-control px-2 py-1.5 text-sm no-underline",
                        collapsed && "justify-center",
                        isActive ? "bg-accent text-accent-foreground" : "text-foreground hover:bg-muted",
                      )
                    }
                  >
                    {r.icon && <r.icon size={16} aria-hidden="true" />}
                    {!collapsed && r.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col gap-2">
          {!collapsed && (
            <>
              <div className="header-slot" id="status-slot"><StatusIndicator /></div>
              <div className="header-slot" id="alert-slot"><AlertBadge /></div>
            </>
          )}
          <button
            type="button"
            onClick={() => setTheme(nextTheme)}
            title={`Theme: ${theme}`}
            className="cursor-pointer rounded-control border border-border bg-transparent p-1.5 text-sm text-foreground hover:bg-muted"
          >
            {collapsed ? theme[0].toUpperCase() : `Theme: ${theme}`}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
      <CommandPalette />
      <Toaster theme={theme} />
    </div>
  );
}
