import { NavLink } from "react-router-dom";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { NAV_GROUPS, routes } from "@/routes";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  theme: ThemeChoice;
  onToggleTheme: () => void;
}

/** Phone "More" tab: every nav route not in the bottom tab bar, plus the theme toggle. */
export default function MoreSheet({ open, onOpenChange, theme, onToggleTheme }: Props) {
  const items = routes.filter((r) => r.nav && !r.phoneTab);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby={undefined}
        className="bottom-0 left-0 top-auto max-h-[85vh] w-full translate-x-0 overflow-y-auto rounded-b-none border-x-0 border-b-0 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]"
      >
        <DialogTitle className="px-2 pb-2 text-base font-semibold">More</DialogTitle>
        <DialogDescription className="sr-only">Other pages and the theme</DialogDescription>
        <nav className="flex flex-col gap-3" aria-label="More pages">
          {NAV_GROUPS.map((g) => {
            const group = items.filter((r) => r.group === g);
            if (group.length === 0) return null;
            return (
              <div key={g} className="flex flex-col gap-0.5">
                <div className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{g}</div>
                {group.map((r) => (
                  <NavLink
                    key={r.path}
                    to={r.path}
                    onClick={() => onOpenChange(false)}
                    className={({ isActive }) =>
                      cn(
                        "flex min-h-11 items-center gap-3 rounded-control px-2 text-sm no-underline",
                        isActive ? "bg-accent text-accent-foreground" : "text-foreground hover:bg-muted",
                      )
                    }
                  >
                    {r.icon && <r.icon size={18} aria-hidden="true" />}
                    {r.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <button
          type="button"
          onClick={onToggleTheme}
          className="mt-3 min-h-11 w-full cursor-pointer rounded-control border border-border bg-transparent px-2 text-sm text-foreground hover:bg-muted"
        >
          Theme: {theme}
        </button>
      </DialogContent>
    </Dialog>
  );
}
