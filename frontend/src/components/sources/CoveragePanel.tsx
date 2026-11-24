import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { Coverage } from "../../api/types";
import { Select } from "@/components/ui/select";

const CAPS = ["bars", "index", "fundamentals", "quarters"];

export default function CoveragePanel({ labels, refreshKey }: { labels: Record<string, string>; refreshKey: number }) {
  const [cap, setCap] = useState("bars");
  const [rows, setRows] = useState<Coverage[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<Coverage[]>(`/sources/coverage?capability=${cap}`)
      .then((r) => live && (setRows(r), setError(null)))
      .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [cap, refreshKey]);

  return (
    <section>
      <h2>Coverage</h2>
      <p>
        <label>
          Data{" "}
          <Select value={cap} onChange={(e) => setCap(e.target.value)}>
            {CAPS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </label>
      </p>
      {error && <p className="neg">{error}</p>}
      {rows.length === 0 ? (
        <p className="muted">Nothing loaded yet.</p>
      ) : (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>{cap === "index" ? "Indexes" : "Symbols"}</th>
              <th>First date</th>
              <th>Last date</th>
              <th>Rows</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.source}>
                <td>{labels[r.source] ?? r.source}</td>
                <td className="num">{r.symbols.toLocaleString("en-IN")}</td>
                <td>{r.first_date}</td>
                <td>{r.last_date}</td>
                <td className="num">{r.rows.toLocaleString("en-IN")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}
