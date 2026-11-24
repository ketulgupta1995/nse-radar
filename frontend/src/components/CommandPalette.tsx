import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { SymbolInfo } from "@/api/types";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useIsPhone } from "@/lib/useIsPhone";
import { routes } from "@/routes";

/** Ctrl+K / Cmd+K: jump to a page or search for a stock. */
export default function CommandPalette() {
  const nav = useNavigate();
  const phone = useIsPhone();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setSymbols([]);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      api
        .get<SymbolInfo[]>(`/symbols/search?q=${encodeURIComponent(term)}`)
        .then((r) => {
          if (!stale) setSymbols(r);
        })
        .catch(() => {
          if (!stale) setSymbols([]);
        });
    }, 200);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [q]);

  const close = (o: boolean) => {
    setOpen(o);
    if (!o) {
      setQ("");
      setSymbols([]);
    }
  };
  const go = (path: string) => {
    close(false);
    nav(path);
  };

  const term = q.trim().toLowerCase();
  const pages = routes.filter((r) => r.nav && (!term || r.label.toLowerCase().includes(term)));

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        aria-describedby={undefined}
        className={
          phone
            ? "inset-0 top-0 left-0 flex h-dvh w-full translate-x-0 flex-col rounded-none border-0 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
            : undefined
        }
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Jump to a page or find a stock</DialogDescription>
        <Command shouldFilter={false} className={phone ? "min-h-0 flex-1" : undefined}>
          <div className="flex items-center">
            <CommandInput
              value={q}
              onValueChange={setQ}
              placeholder="Find a stock or jump to a page…"
              aria-label="Find a stock or page"
              autoFocus
              className={phone ? "min-h-12 text-base" : undefined}
            />
            {phone && (
              <button
                type="button"
                onClick={() => close(false)}
                aria-label="Close search"
                className="flex size-12 flex-none cursor-pointer items-center justify-center border-0 border-b border-border bg-transparent text-muted-foreground"
              >
                <X size={20} />
              </button>
            )}
          </div>
          <CommandList className={phone ? "max-h-none flex-1 [&_[cmdk-item]]:min-h-11" : undefined}>
            <CommandEmpty>Nothing found.</CommandEmpty>
            {symbols.length > 0 && (
              <CommandGroup heading="Stocks">
                {symbols.map((s) => (
                  <CommandItem key={s.symbol} value={`stock-${s.symbol}`} onSelect={() => go(`/stock/${s.symbol}`)}>
                    <strong className="font-mono">{s.symbol}</strong>
                    <span className="text-muted-foreground">{s.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {pages.length > 0 && (
              <CommandGroup heading="Pages">
                {pages.map((r) => (
                  <CommandItem key={r.path} value={`page-${r.path}`} onSelect={() => go(r.path)}>
                    {r.icon && <r.icon size={16} aria-hidden="true" />}
                    {r.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
