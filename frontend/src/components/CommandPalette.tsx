import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { SymbolInfo } from "@/api/types";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { routes } from "@/routes";

/** Ctrl+K / Cmd+K: jump to a page or search for a stock. */
export default function CommandPalette() {
  const nav = useNavigate();
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
      <DialogContent aria-describedby={undefined}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Jump to a page or find a stock</DialogDescription>
        <Command shouldFilter={false}>
          <CommandInput value={q} onValueChange={setQ} placeholder="Find a stock or jump to a page…" aria-label="Find a stock or page" />
          <CommandList>
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
