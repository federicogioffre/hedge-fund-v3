import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RebalanceResponse } from "../types";

export function RebalancePanel() {
  const [dryRun, setDryRun] = useState(true);
  const [result, setResult] = useState<RebalanceResponse | null>(null);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => api.rebalance(dryRun),
    onSuccess: (res) => {
      setResult(res);
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });

  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">
          REBALANCE
        </h2>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="accent-accent"
          />
          Dry run (no orders)
        </label>
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className={`w-full rounded px-4 py-2 text-sm font-medium ${
          dryRun
            ? "bg-accent/10 text-accent border border-accent/40 hover:bg-accent/20"
            : "bg-warn/20 text-warn border border-warn/40 hover:bg-warn/30"
        } disabled:opacity-50`}
      >
        {mutation.isPending
          ? "Running…"
          : dryRun
          ? "▶ Run Dry-Run"
          : "⚡ Execute Rebalance"}
      </button>

      {mutation.isError && (
        <div className="mt-2 text-xs text-danger">
          {(mutation.error as Error).message}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-muted">Mode</span>
            <span>{result.dry_run ? "dry-run" : "live"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Status</span>
            <span>{result.status}</span>
          </div>
          {result.message && (
            <div className="rounded bg-warn/10 p-2 text-warn">
              {result.message}
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-muted">Executed</span>
            <span className="text-accent">{result.executed_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Skipped</span>
            <span className="text-muted">{result.skipped_count}</span>
          </div>

          {result.executed.length > 0 && (
            <div className="mt-2 rounded border border-border p-2">
              <div className="mb-1 text-muted">EXECUTED</div>
              {result.executed.map((o, i) => (
                <div key={i} className="flex justify-between py-0.5">
                  <span>
                    <span className="font-semibold">{o.ticker}</span>{" "}
                    <span
                      className={
                        o.side === "buy" ? "text-accent" : "text-danger"
                      }
                    >
                      {o.side}
                    </span>
                  </span>
                  <span>${o.notional.toFixed(0)}</span>
                </div>
              ))}
            </div>
          )}

          {result.skipped.length > 0 && (
            <details className="mt-2 rounded border border-border p-2">
              <summary className="cursor-pointer text-muted">
                SKIPPED ({result.skipped.length})
              </summary>
              <div className="mt-2 space-y-1">
                {result.skipped.map((s, i) => (
                  <div key={i} className="flex justify-between">
                    <span>{s.ticker}</span>
                    <span className="text-muted">{s.reason}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
