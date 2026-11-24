import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { PriceCheck, UnparsedAction } from "../../api/types";
import { shortDay } from "../../lib/dates";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useIsPhone } from "@/lib/useIsPhone";

interface Props {
  labels: Record<string, string>;
  onChanged: () => void;
}

const KIND_LABEL: Record<PriceCheck["kind"], string> = {
  mismatch: "Sources disagree",
  unexplained_gap: "Unexplained jump",
  adjustment_jump: "Odd jump on an adjustment date",
};

export function explain(c: PriceCheck, labels: Record<string, string>): string {
  const name = (s: string | null) => (s ? (labels[s] ?? s) : "the other source");
  if (c.kind === "unexplained_gap") {
    return `Price jumped ${Math.abs(c.detail.change_pct ?? 0).toFixed(0)}% in a day with no corporate action.`;
  }
  const f = c.detail.suggested_factor;
  if (c.kind === "adjustment_jump") {
    const move = c.detail.open_move_pct ?? 0;
    const pct = `${move > 0 ? "+" : ""}${move.toFixed(0)}`;
    const applied = c.detail.applied_factor?.toFixed(2) ?? "?";
    const suggested = f?.toFixed(2) ?? "?";
    return `Adjusted price moved ${pct}% at the open on a split/bonus/demerger date: the factor ×${applied} looks wrong; ×${suggested} would remove the jump.`;
  }
  const by = f ? `×${f.toFixed(2)}` : "a different amount";
  return `${name(c.primary_source)} and ${name(c.other_source)} disagree by ${by} from this date: probably a split or bonus that wasn't listed.`;
}

export default function DataChecks({ labels, onChanged }: Props) {
  const phone = useIsPhone();
  const [checks, setChecks] = useState<PriceCheck[]>([]);
  const [unparsed, setUnparsed] = useState<UnparsedAction[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [showFixed, setShowFixed] = useState(false);
  const [factors, setFactors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const statuses = ["open", ...(showIgnored ? ["ignored"] : []), ...(showFixed ? ["fixed"] : [])];
      const [lists, u] = await Promise.all([
        Promise.all(statuses.map((s) => api.get<PriceCheck[]>(`/data/checks?status=${s}`))),
        api.get<UnparsedAction[]>("/data/unparsed-actions"),
      ]);
      setChecks(lists.flat());
      setUnparsed(u);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [showIgnored, showFixed]);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
    await load();
    onChanged();
  }

  const key = (u: UnparsedAction) => `${u.source}|${u.symbol}|${u.ex_date}|${u.subject}`;

  return (
    <div>
      {error && <p className="neg">{error}</p>}
      <h2>Price checks</h2>
      <p>
        <label>
          <input type="checkbox" checked={showIgnored} onChange={(e) => setShowIgnored(e.target.checked)} /> Show ignored
        </label>{" "}
        <label>
          <input type="checkbox" checked={showFixed} onChange={(e) => setShowFixed(e.target.checked)} /> Show fixed
        </label>
      </p>
      {checks.length === 0 ? (
        <p className="muted">No data issues. 🎉</p>
      ) : phone ? (
        checks.map((c) => (
          <div key={c.id} className="mb-3 rounded-md border border-border p-3">
            <p>
              <Link to={`/stock/${c.symbol}`}>{c.symbol}</Link> · {shortDay(c.date)} · <b>{KIND_LABEL[c.kind]}</b>
            </p>
            <p>
              {explain(c, labels)}
              {c.status !== "open" && <span className="muted"> ({c.status})</span>}
            </p>
            {c.status === "open" && (
              <div className="flex flex-wrap gap-2">
                {((c.kind === "mismatch" && c.detail.ex_date) || c.kind === "adjustment_jump") && c.detail.suggested_factor && (
                  <Button variant="outline" size="sm" type="button" onClick={() => act(() => api.post(`/data/checks/${c.id}`, { action: "apply_factor" }))}>
                    Apply suggested factor
                  </Button>
                )}
                <Button variant="outline" size="sm" type="button" onClick={() => act(() => api.post(`/data/checks/${c.id}`, { action: "ignore" }))}>
                  Ignore
                </Button>
              </div>
            )}
          </div>
        ))
      ) : (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Stock</th>
              <th>Date</th>
              <th>Kind</th>
              <th>What we saw</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {checks.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/stock/${c.symbol}`}>{c.symbol}</Link>
                </td>
                <td>{shortDay(c.date)}</td>
                <td>{KIND_LABEL[c.kind]}</td>
                <td>
                  {explain(c, labels)}
                  {c.status !== "open" && <span className="muted"> ({c.status})</span>}
                </td>
                <td>
                  {c.status === "open" && (
                    <>
                      {((c.kind === "mismatch" && c.detail.ex_date) || c.kind === "adjustment_jump") &&
                        c.detail.suggested_factor && (
                        <Button variant="outline" size="sm"
                          type="button"
                          onClick={() => act(() => api.post(`/data/checks/${c.id}`, { action: "apply_factor" }))}
                        >
                          Apply suggested factor
                        </Button>
                      )}{" "}
                      <Button variant="outline" size="sm" type="button" onClick={() => act(() => api.post(`/data/checks/${c.id}`, { action: "ignore" }))}>
                        Ignore
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      <h2>Corporate actions we couldn't read</h2>
      <p className="muted">
        If one of these was a split or bonus, enter the factor to multiply older prices by (a 1:1 bonus is 0.5, a 10→2 split is
        0.2).
      </p>
      {unparsed.length === 0 ? (
        <p className="muted">None.</p>
      ) : phone ? (
        unparsed.map((u) => {
          const k = key(u);
          const f = Number(factors[k]);
          return (
            <div key={k} className="mb-3 rounded-md border border-border p-3">
              <p>
                <Link to={`/stock/${u.symbol}`}>{u.symbol}</Link> · ex-date {shortDay(u.ex_date)}
              </p>
              <p>{u.subject}</p>
              <div className="flex items-center gap-2">
                <Input
                  className="flex-1"
                  aria-label={`Factor for ${u.symbol} ${u.ex_date}`}
                  inputMode="decimal"
                  placeholder="Factor"
                  value={factors[k] ?? ""}
                  onChange={(e) => setFactors({ ...factors, [k]: e.target.value })}
                />
                <Button
                  variant="outline"
                  size="sm"
                  type="button"
                  disabled={!(f > 0)}
                  onClick={() =>
                    act(async () => {
                      await api.post("/data/manual-adjustment", { symbol: u.symbol, ex_date: u.ex_date, factor: f });
                      setSaved((s) => new Set(s).add(k));
                    })
                  }
                >
                  Save
                </Button>
                {saved.has(k) && <span className="pos"> saved</span>}
              </div>
            </div>
          );
        })
      ) : (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Stock</th>
              <th>Ex-date</th>
              <th>Wording</th>
              <th>Factor</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {unparsed.map((u) => {
              const k = key(u);
              const f = Number(factors[k]);
              return (
                <tr key={k}>
                  <td>
                    <Link to={`/stock/${u.symbol}`}>{u.symbol}</Link>
                  </td>
                  <td>{shortDay(u.ex_date)}</td>
                  <td>{u.subject}</td>
                  <td>
                    <Input
                      aria-label={`Factor for ${u.symbol} ${u.ex_date}`}
                      inputMode="decimal"
                      size={6}
                      value={factors[k] ?? ""}
                      onChange={(e) => setFactors({ ...factors, [k]: e.target.value })}
                    />
                  </td>
                  <td>
                    <Button variant="outline" size="sm"
                      type="button"
                      disabled={!(f > 0)}
                      onClick={() =>
                        act(async () => {
                          await api.post("/data/manual-adjustment", { symbol: u.symbol, ex_date: u.ex_date, factor: f });
                          setSaved((s) => new Set(s).add(k));
                        })
                      }
                    >
                      Save
                    </Button>
                    {saved.has(k) && <span className="pos"> saved</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
