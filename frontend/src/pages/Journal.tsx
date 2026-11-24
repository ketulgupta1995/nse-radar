import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type { GroupStats, JournalStats, Position } from "../api/types";
import Explain from "../components/Explain";
import Num from "../components/Num";
import TradeCard from "../components/positions/TradeCard";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

/** "Trades entered with FOMO: 3, win rate 0%" for every mood other than calm. */
export function insights(byEmotion: Record<string, GroupStats>): string[] {
  return Object.entries(byEmotion)
    .filter(([e]) => e !== "calm")
    .map(([e, g]) => `Trades entered with ${e}: ${g.n}, win rate ${Math.round(g.win_rate)}%`);
}

function Stat({ label, help, children }: { label: string; help: string; children: React.ReactNode }) {
  return (
    <Card className="flex flex-col gap-1 p-3">
      <div className="text-xs text-muted-foreground">
        {label}
        <Explain text={help} />
      </div>
      <div className="text-lg font-semibold">{children}</div>
    </Card>
  );
}

interface GroupRow {
  name: string;
  g: GroupStats;
}

function GroupTable({ title, rows }: { title: string; rows: Record<string, GroupStats> }) {
  const data = useMemo<GroupRow[]>(() => Object.entries(rows).map(([name, g]) => ({ name, g })), [rows]);
  const columns = useMemo<ColumnDef<GroupRow>[]>(
    () => [
      { accessorKey: "name", header: "" },
      { id: "n", header: "Trades", meta: { right: true }, accessorFn: (r) => r.g.n, cell: ({ row }) => <span className="num">{row.original.g.n}</span> },
      { id: "win", header: "Win rate", meta: { right: true }, accessorFn: (r) => r.g.win_rate, cell: ({ row }) => <span className="num">{row.original.g.win_rate}%</span> },
      { id: "r", header: "Average R", meta: { right: true }, sortUndefined: "last", accessorFn: (r) => r.g.avg_r ?? undefined, cell: ({ row }) => <span className="num">{row.original.g.avg_r ?? "—"}</span> },
    ],
    [],
  );
  if (data.length === 0) return null;
  return (
    <Card className="min-w-0 flex-1">
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <DataTable columns={columns} data={data} getRowId={(r) => r.name} />
    </Card>
  );
}

export default function Journal() {
  const [stats, setStats] = useState<JournalStats | null>(null);
  const [trades, setTrades] = useState<Position[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState("all");

  useEffect(() => {
    Promise.all([api.get<JournalStats>("/journal/stats"), api.get<Position[]>("/positions?status=closed")])
      .then(([s, t]) => {
        setStats(s);
        setTrades([...t].sort((a, b) => (b.exit_date ?? "").localeCompare(a.exit_date ?? "")));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (error) return <p className="neg">{error}</p>;
  if (!stats || !trades)
    return (
      <div>
        <h1>Journal</h1>
        <Skeleton className="h-32" />
      </div>
    );
  if (stats.closed === 0) {
    return (
      <div>
        <h1>Journal</h1>
        <EmptyState title="No closed trades yet.">When you close a position, what you learned shows up here.</EmptyState>
      </div>
    );
  }

  const years = [...new Set(trades.map((t) => (t.exit_date ?? "").slice(0, 4)).filter(Boolean))].sort().reverse();
  const shown = year === "all" ? trades : trades.filter((t) => t.exit_date?.startsWith(year));
  const lines = insights(stats.by_emotion);

  return (
    <div>
      <h1>Journal</h1>
      <p className="muted">Statistics below cover all closed trades.</p>
      <div className="mb-4 grid grid-cols-5 gap-3">
        <Stat label="Closed trades" help="How many trades you have finished. Small numbers prove little, so be careful drawing conclusions under about 30.">
          {stats.closed}
        </Stat>
        <Stat label="Win rate" help="Share of closed trades that made money. A low win rate can still be profitable if wins are bigger than losses.">
          {stats.win_rate}%
        </Stat>
        <Stat label="Average R" help="Average profit in units of the risk you took per trade. Above 0 means you make more than you risk, on average.">
          {stats.avg_r ?? "—"}
        </Stat>
        <Stat label="Average win vs loss" help="Typical % gain on winning trades compared with the typical % loss on losing trades.">
          <Num value={stats.avg_win_pct} kind="pct" colored /> / <Num value={stats.avg_loss_pct} kind="pct" colored />
        </Stat>
        <Stat label="Thesis was right" help="How often you judged your original reason for buying to be correct, whether or not the trade made money.">
          {stats.thesis_right_pct ?? "—"}%
        </Stat>
      </div>

      {lines.length > 0 && (
        <ul className="insights">
          {lines.map((l) => <li key={l}>{l}</li>)}
        </ul>
      )}
      <div className="mb-4 flex gap-4">
        <GroupTable title="By exit reason" rows={stats.by_exit_reason} />
        <GroupTable title="By how I felt when buying" rows={stats.by_emotion} />
      </div>

      <h2>Trades</h2>
      <label className="mb-2 flex items-center gap-2">
        <span>Year </span>
        <Select value={year} onChange={(e) => setYear(e.target.value)}>
          <option value="all">All</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </Select>
      </label>
      <div className="flex flex-col gap-2">
        {shown.map((t) => <TradeCard key={t.id} position={t} />)}
      </div>
    </div>
  );
}
