import type { LucideIcon } from "lucide-react";
import {
  Bell,
  BookOpen,
  Database,
  Filter,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  ListChecks,
  Settings as SettingsIcon,
  Star,
  Wallet,
} from "lucide-react";
import type { JSX } from "react";
import Alerts from "./pages/Alerts";
import Backtests from "./pages/Backtests";
import Dashboard from "./pages/Dashboard";
import Journal from "./pages/Journal";
import NotFound from "./pages/NotFound";
import Jobs from "./pages/Jobs";
import Portfolio from "./pages/Portfolio";
import Screener from "./pages/Screener";
import Settings from "./pages/Settings";
import Sources from "./pages/Sources";
import Stock from "./pages/Stock";
import TrackRecord from "./pages/TrackRecord";
import Watchlist from "./pages/Watchlist";

export interface AppRoute {
  path: string;
  label: string;
  nav: boolean;
  /** Sidebar section and icon; required for entries with nav: true. */
  group?: NavGroup;
  icon?: LucideIcon;
  /** Position (1–4) in the phone bottom tab bar; other nav routes go in "More". */
  phoneTab?: number;
  element: JSX.Element;
}

export type NavGroup = "Research" | "Money" | "Validate" | "System";
export const NAV_GROUPS: NavGroup[] = ["Research", "Money", "Validate", "System"];

// Add a page by adding one entry here. Nav order = array order.
export const routes: AppRoute[] = [
  { path: "/", label: "Dashboard", nav: true, group: "Research", icon: LayoutDashboard, phoneTab: 1, element: <Dashboard /> },
  { path: "/screener", label: "Screener", nav: true, group: "Research", icon: Filter, phoneTab: 2, element: <Screener /> },
  { path: "/watchlist", label: "Watchlist", nav: true, group: "Research", icon: Star, phoneTab: 3, element: <Watchlist /> },
  { path: "/stock/:symbol", label: "Stock", nav: false, element: <Stock /> },
  { path: "/positions", label: "Portfolio", nav: true, group: "Money", icon: Wallet, phoneTab: 4, element: <Portfolio /> },
  { path: "/journal", label: "Journal", nav: true, group: "Money", icon: BookOpen, element: <Journal /> },
  { path: "/backtests", label: "Backtests", nav: true, group: "Validate", icon: FlaskConical, element: <Backtests /> },
  { path: "/backtests/new", label: "New backtest", nav: false, element: <Backtests /> },
  { path: "/backtests/:id", label: "Backtest", nav: false, element: <Backtests /> },
  { path: "/track-record", label: "Track record", nav: true, group: "Validate", icon: LineChart, element: <TrackRecord /> },
  { path: "/jobs", label: "Jobs", nav: true, group: "System", icon: ListChecks, element: <Jobs /> },
  { path: "/sources", label: "Sources", nav: true, group: "System", icon: Database, element: <Sources /> },
  { path: "/alerts", label: "Alerts", nav: true, group: "Money", icon: Bell, element: <Alerts /> },
  { path: "/settings", label: "Settings", nav: true, group: "System", icon: SettingsIcon, element: <Settings /> },
  { path: "*", label: "Not found", nav: false, element: <NotFound /> }, // keep last
];
