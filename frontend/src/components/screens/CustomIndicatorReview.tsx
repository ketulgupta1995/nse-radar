import { useState } from "react";
import { ApiError, api } from "../../api/client";
import type { CustomIndicator } from "../../api/types";
import Explain from "../Explain";
import Modal from "../checklist/Modal";
import { Button } from "@/components/ui/button";

interface Props {
  indicator: CustomIndicator;
  onClose: () => void;
  /** Called after a successful approval (the owner closes the modal afterwards). */
  onApproved?: (c: CustomIndicator) => void;
  /** Called after Reject. */
  onRejected?: (c: CustomIndicator) => void;
}

const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

export default function CustomIndicatorReview({ indicator, onClose, onApproved, onRejected }: Props) {
  const [current, setCurrent] = useState(indicator);
  const [busy, setBusy] = useState(false);
  const [trialError, setTrialError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const lines = current.code.split("\n");
  const pending = current.status === "pending";
  const blocked = current.problems.length > 0;

  const approve = async () => {
    setBusy(true);
    setTrialError(null);
    try {
      const r = await api.post<CustomIndicator>(`/custom-indicators/${current.id}/approve`);
      setCurrent(r);
      setDone(true);
      onApproved?.(r);
    } catch (e) {
      setTrialError(msg(e)); // the indicator stays pending
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      const r = await api.post<CustomIndicator>(`/custom-indicators/${current.id}/reject`);
      setCurrent(r);
      onRejected?.(r);
      onClose();
    } catch (e) {
      setTrialError(msg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Review indicator: ${current.name}`} onClose={onClose}>
      <p>{current.explain}</p>
      <h3>Settings it uses</h3>
      {current.params_schema.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul>
          {current.params_schema.map((p) => (
            <li key={p.name}>
              {p.label} (<code>{p.name}</code>): starts at {p.default}
              {p.min !== undefined && p.max !== undefined ? `, between ${p.min} and ${p.max}` : ""}
            </li>
          ))}
        </ul>
      )}

      <h3>
        The code <Explain text="This is the exact program Claude wrote. It has not been run. Read it before approving." />
      </h3>
      <pre aria-label="Indicator code" style={{ overflow: "auto", fontFamily: "monospace", fontSize: "0.85em" }}>
        {lines.map((line, i) => (
          <div key={i}>
            <span className="muted" style={{ userSelect: "none" }}>{String(i + 1).padStart(3, " ")}  </span>
            {line}
          </div>
        ))}
      </pre>

      <h3>
        Safety check <Explain text="An automatic check that the code only does maths on prices: no files, no internet, no imports." />
      </h3>
      {blocked ? (
        <ul className="neg">{current.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
      ) : (
        <p className="pos">Passed. The code has not run yet, so there are no sample values until you approve.</p>
      )}

      {done && current.sample && (
        <div role="status">
          <p className="pos"><strong>Approved.</strong> Trial run on made-up prices, last 5 values:</p>
          <p className="num">{current.sample.map((v) => (v === null ? "–" : v.toFixed(2))).join(", ")}</p>
        </div>
      )}
      {trialError && (
        <p className="neg" role="alert">
          Could not approve: {trialError}
          {pending && " The indicator is still pending."}
        </p>
      )}

      {pending && !done && (
        <p>
          Approving lets this code run on your laptop. Only approve if you've read it. It may only do maths on prices.
        </p>
      )}
      <div className="modal-foot">
        {done ? (
          <Button variant="outline" size="sm" onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="outline" size="sm" disabled={busy || !pending || blocked} onClick={() => void approve()}>Approve</Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void reject()}>Reject</Button>
          </>
        )}
      </div>
    </Modal>
  );
}
