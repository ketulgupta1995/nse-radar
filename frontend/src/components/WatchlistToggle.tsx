import { useState } from "react";
import { api } from "../api/client";

interface Props {
  symbol: string;
  initial: boolean;
  onChange?: (watching: boolean) => void;
}

export default function WatchlistToggle({ symbol, initial, onChange }: Props) {
  const [on, setOn] = useState(initial);
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      if (on) await api.del(`/watchlist/${symbol}`);
      else await api.post("/watchlist", { symbol });
      setOn(!on);
      onChange?.(!on);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      className="star"
      disabled={busy}
      aria-pressed={on}
      title={on ? "Remove from watchlist" : "Add to watchlist"}
      onClick={() => void toggle()}
    >
      {on ? "★" : "☆"} {on ? "Watching" : "Watch"}
    </button>
  );
}
