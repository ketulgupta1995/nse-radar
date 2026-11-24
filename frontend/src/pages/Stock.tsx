import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { FundField, Fundamentals, IndicatorDef, Position, PriceSeries, SourceInfo, SymbolInfo } from "../api/types";
import IndicatorPicker, { loadSelection, saveSelection } from "../components/chart/IndicatorPicker";
import PriceChart from "../components/chart/PriceChart";
import AskClaude from "../components/ai/AskClaude";
import Markdown from "../components/ai/Markdown";
import EntryChecklist from "../components/checklist/EntryChecklist";
import ExitChecklist from "../components/checklist/ExitChecklist";
import Explain from "../components/Explain";
import Num from "../components/Num";
import Announcements from "../components/stock/Announcements";
import NewsList from "../components/stock/NewsList";
import FundamentalsPanel from "../components/stock/FundamentalsPanel";
import QuarterlyTable from "../components/stock/QuarterlyTable";
import ShareholdingMini from "../components/stock/ShareholdingMini";
import WatchlistToggle from "../components/WatchlistToggle";
import ResultsBadge from "../components/ResultsBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useIsPhone } from "@/lib/useIsPhone";
import { ClipboardCheck, MoreHorizontal, Sparkles, XCircle } from "lucide-react";

// Fetch five years once; the chart's timeframe buttons only change what part of it is visible.
const HISTORY_DAYS = 1826;

function startFor(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

interface PastAsk {
  id: number;
  kind: string;
  status: string;
  response: string | null;
  created_at: string;
}

const ASK_LABELS: Record<string, string> = { stock_brief: "Brief", thesis_draft: "Draft thesis", checklist_challenge: "Challenge" };

export default function Stock() {
  const { symbol = "" } = useParams();
  const [info, setInfo] = useState<SymbolInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [catalogue, setCatalogue] = useState<IndicatorDef[]>([]);
  const [active, setActive] = useState<string[]>(loadSelection);
  const [series, setSeries] = useState<PriceSeries | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"entry" | "exit" | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [reload, setReload] = useState(0);
  const [fundFields, setFundFields] = useState<FundField[]>([]);
  const [fund, setFund] = useState<Fundamentals | null>(null);
  const [tab, setTab] = useState<"announcements" | "news">("announcements");
  const [past, setPast] = useState<PastAsk[]>([]);
  const [askTick, setAskTick] = useState(0);
  const phone = useIsPhone();
  const [phoneTab, setPhoneTab] = useState("overview");
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    api
      .get<PastAsk[]>(`/ai/requests?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => setPast(r.filter((x) => x.status === "done" && x.response)))
      .catch(() => undefined);
  }, [symbol, askTick]);

  useEffect(() => {
    api.get<IndicatorDef[]>("/indicators").then(setCatalogue).catch(() => undefined);
    api
      .get<SourceInfo[]>("/sources")
      .then((s) => setLabels(Object.fromEntries(s.map((x) => [x.name, x.label]))))
      .catch(() => undefined);
    api.get<FundField[]>("/fundamentals/fields").then(setFundFields).catch(() => undefined);
  }, []);

  useEffect(() => {
    setFund(null);
    api
      .get<Fundamentals>(`/fundamentals/${encodeURIComponent(symbol)}`)
      .then(setFund)
      .catch(() => undefined);
  }, [symbol]);

  useEffect(() => {
    setInfo(null);
    setError(null);
    api
      .get<SymbolInfo>(`/symbols/${encodeURIComponent(symbol)}`)
      .then(setInfo)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [symbol, reload]);

  useEffect(() => {
    setPosition(null);
    if (!info?.open_position_id) return;
    api
      .get<Position[]>("/positions?status=open")
      .then((all) => setPosition(all.find((p) => p.id === info.open_position_id) ?? null))
      .catch(() => undefined);
  }, [info?.open_position_id]);

  useEffect(() => {
    const q = new URLSearchParams({ start: startFor(HISTORY_DAYS), indicators: active.join(",") });
    let stale = false;
    api
      .get<PriceSeries>(`/prices/${encodeURIComponent(symbol)}?${q}`)
      .then((s) => {
        if (!stale) {
          setSeries(s);
          setChartError(null);
        }
      })
      .catch((e) => !stale && setChartError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      stale = true;
    };
  }, [symbol, active]);

  const changeActive = (v: string[]) => {
    setActive(v);
    saveSelection(v);
  };

  if (error) return <p className="neg">{error}</p>;
  if (!info)
    return (
      <div className="flex flex-col gap-3" aria-label="Loading">
        <Skeleton className="h-12" />
        <Skeleton className="h-96" />
      </div>
    );
  const chartCard = (
    <Card>
      <IndicatorPicker catalogue={catalogue} value={active} onChange={changeActive} />
      {chartError && <p className="neg">{chartError}</p>}
      {!series && !chartError && <Skeleton className="mt-2 h-80" />}
      {series && series.bars.length > 0 && <PriceChart data={series} active={active} catalogue={catalogue} />}
      {series && series.bars.length === 0 && <EmptyState title="No prices for this stock yet." className="mt-2" />}
    </Card>
  );
  const newsPanel = (
    <section aria-label="Announcements and news">
      <div className="mb-2 flex gap-1" role="group" aria-label="News type">
        {(["announcements", "news"] as const).map((t) => (
          <Button key={t} variant={tab === t ? "default" : "outline"} size="sm" aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t === "announcements" ? "Announcements" : "News"}
          </Button>
        ))}
      </div>
      {tab === "announcements" ? <Announcements symbol={info.symbol} /> : <NewsList symbol={info.symbol} />}
    </section>
  );
  const askPanel = (
    <section aria-label="Ask Claude">
      <AskClaude kind="stock_brief" symbol={info.symbol} label="Brief" onDone={() => setAskTick((n) => n + 1)} />
      <AskClaude kind="thesis_draft" symbol={info.symbol} label="Draft thesis" onDone={() => setAskTick((n) => n + 1)} />
      {past.length > 0 && (
        <>
          <h3>Past responses</h3>
          {past.map((p) => (
            <details key={p.id}>
              <summary>{ASK_LABELS[p.kind] ?? p.kind} · {p.created_at.slice(0, 16).replace("T", " ")}</summary>
              <Markdown text={p.response ?? ""} />
            </details>
          ))}
        </>
      )}
    </section>
  );
  const phoneHeader = (
    <header className="sticky top-0 z-20 -mx-4 -mt-4 mb-3 flex flex-col gap-1 border-b border-border bg-background px-4 py-2">
      <div className="flex items-center gap-2">
        <h1 className="m-0 min-w-0 flex-1 truncate text-lg">
          <span className="font-mono">{info.symbol}</span> <span className="muted text-sm font-normal">{info.name}</span>
        </h1>
        <WatchlistToggle key={info.symbol} symbol={info.symbol} initial={Boolean(info.in_watchlist)} />
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {info.last_close != null && (
          <span className="font-semibold">
            <Num value={info.last_close} kind="inr" digits={2} delta={info.change_pct} />
          </span>
        )}
        {info.change_pct != null && <Num value={info.change_pct} kind="pct" colored />}
        {info.bars_source && <Badge>data: {labels[info.bars_source] ?? info.bars_source}</Badge>}
        {info.trade_for_trade && <Badge variant="warning">Trade-for-trade</Badge>}
        <ResultsBadge next={info.next_results} />
        <div className="ml-auto flex items-center gap-1">
          {position ? (
            <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Close position" title="Close position" onClick={() => setDialog("exit")}>
              <XCircle size={18} aria-hidden="true" />
            </Button>
          ) : (
            <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Start checklist" title="Start checklist" onClick={() => setDialog("entry")}>
              <ClipboardCheck size={18} aria-hidden="true" />
            </Button>
          )}
          <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Ask Claude" title="Ask Claude" onClick={() => setPhoneTab("ai")}>
            <Sparkles size={18} aria-hidden="true" />
          </Button>
          <Button variant="outline" size="icon" className="h-10 w-10" aria-label="More" aria-expanded={menu} title="More" onClick={() => setMenu((m) => !m)}>
            <MoreHorizontal size={18} aria-hidden="true" />
          </Button>
        </div>
      </div>
      {menu && (
        <div className="flex flex-wrap gap-3 py-1 text-sm">
          <a href={`https://www.screener.in/company/${encodeURIComponent(info.symbol.toUpperCase())}/consolidated/`} target="_blank" rel="noopener noreferrer">Screener.in ↗</a>
          <a href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(`NSE:${info.symbol.toUpperCase()}`)}`} target="_blank" rel="noopener noreferrer">TradingView ↗</a>
          {position && <span>Open position: {position.qty} @ <Num value={position.entry_price} kind="inr" digits={2} /></span>}
        </div>
      )}
    </header>
  );
  const phoneBody = (
    <div className="flex min-w-0 flex-col gap-3">
      {chartCard}
      <Tabs value={phoneTab} onValueChange={setPhoneTab}>
        <TabsList className="overflow-x-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="quarterly">Quarterly</TabsTrigger>
          <TabsTrigger value="news">News</TabsTrigger>
          <TabsTrigger value="ai">AI</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="flex flex-col gap-4">
          <FundamentalsPanel fundamentals={fund} fields={fundFields} labels={labels} />
          <ShareholdingMini fundamentals={fund} labels={labels} />
        </TabsContent>
        <TabsContent value="quarterly">
          <QuarterlyTable fundamentals={fund} labels={labels} />
        </TabsContent>
        <TabsContent value="news">{newsPanel}</TabsContent>
        <TabsContent value="ai">{askPanel}</TabsContent>
      </Tabs>
    </div>
  );
  return (
    <div>
      {phone && phoneHeader}
      {!phone && <header className="sticky top-0 z-20 -mx-6 -mt-6 mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-background px-6 py-3">
        <h1 className="m-0 text-xl">
          <span className="font-mono">{info.symbol}</span> <span className="muted text-base font-normal">{info.name}</span>
        </h1>
        <div className="flex items-baseline gap-2">
          {info.last_close != null && (
            <span className="text-lg font-semibold">
              <Num value={info.last_close} kind="inr" digits={2} delta={info.change_pct} />
            </span>
          )}
          {info.change_pct != null && <Num value={info.change_pct} kind="pct" colored />}
          <span className="muted">{info.last_date ? `as of ${info.last_date}` : "no prices yet"}</span>
          {info.bars_source && <Badge>data: {labels[info.bars_source] ?? info.bars_source}</Badge>}
          {info.trade_for_trade && (
            <span className="inline-flex items-center gap-1">
              <Badge variant="warning">Trade-for-trade</Badge>
              <Explain
                text={`NSE moved this stock to the ${info.series} series: every trade must be delivered (no buying and selling the same day), and it is often under extra surveillance with tighter price limits.`}
              />
            </span>
          )}
          <ResultsBadge next={info.next_results} />
          <a
            href={`https://www.screener.in/company/${encodeURIComponent(info.symbol.toUpperCase())}/consolidated/`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Screener.in ↗
          </a>
          <a
            href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(`NSE:${info.symbol.toUpperCase()}`)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            TradingView ↗
          </a>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <WatchlistToggle key={info.symbol} symbol={info.symbol} initial={Boolean(info.in_watchlist)} />
          {position ? (
            <span className="flex items-center gap-2">
              Open position: {position.qty} @ <Num value={position.entry_price} kind="inr" digits={2} />
              <Button variant="outline" size="sm" onClick={() => setDialog("exit")}>Close…</Button>
            </span>
          ) : (
            <Button onClick={() => setDialog("entry")}>Start checklist</Button>
          )}
        </div>
      </header>}
      {dialog === "entry" && (
        <EntryChecklist
          symbol={info.symbol}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      )}
      {dialog === "exit" && position && (
        <ExitChecklist
          position={position}
          onClose={() => setDialog(null)}
          onClosed={() => {
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      )}
      {phone && phoneBody}
      {!phone && <div className="grid grid-cols-[minmax(0,13fr)_minmax(0,7fr)] items-start gap-4">
        <div className="flex min-w-0 flex-col gap-4">
          {chartCard}
          <QuarterlyTable fundamentals={fund} labels={labels} />
        </div>
        <Card className="min-w-0 p-3">
          <Tabs defaultValue="fundamentals">
            <TabsList>
              <TabsTrigger value="fundamentals">Fundamentals</TabsTrigger>
              <TabsTrigger value="shareholding">Shareholding</TabsTrigger>
              <TabsTrigger value="news">News</TabsTrigger>
              <TabsTrigger value="ask">Ask Claude</TabsTrigger>
            </TabsList>
            <TabsContent value="fundamentals">
              <FundamentalsPanel fundamentals={fund} fields={fundFields} labels={labels} />
            </TabsContent>
            <TabsContent value="shareholding">
              <ShareholdingMini fundamentals={fund} labels={labels} />
            </TabsContent>
            <TabsContent value="news">
              {newsPanel}
            </TabsContent>
            <TabsContent value="ask">
              {askPanel}
            </TabsContent>
          </Tabs>
        </Card>
      </div>}
    </div>
  );
}
