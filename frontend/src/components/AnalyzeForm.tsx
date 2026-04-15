import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function AnalyzeForm() {
  const [ticker, setTicker] = useState("");
  const [assetType, setAssetType] = useState<"equity" | "crypto">("equity");
  const [lastRequest, setLastRequest] = useState<string | null>(null);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: (t: string) => api.analyze(t.trim().toUpperCase(), assetType),
    onSuccess: (res) => {
      setLastRequest(res.request_id);
      setTicker("");
      // Refresh ranking after a short delay so new analysis shows up
      setTimeout(
        () => qc.invalidateQueries({ queryKey: ["ranking"] }),
        3000
      );
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (ticker.trim()) mutation.mutate(ticker);
  };

  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold tracking-wide text-slate-200">
        ANALYZE
      </h2>
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="AAPL, MSFT, BTC…"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          className="flex-1 min-w-[180px] rounded border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none"
        />
        <select
          value={assetType}
          onChange={(e) =>
            setAssetType(e.target.value as "equity" | "crypto")
          }
          className="rounded border border-border bg-bg px-3 py-2 text-sm"
        >
          <option value="equity">equity</option>
          <option value="crypto">crypto</option>
        </select>
        <button
          type="submit"
          disabled={mutation.isPending || !ticker.trim()}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? "Queuing…" : "Analyze"}
        </button>
      </form>

      {mutation.isError && (
        <div className="mt-2 text-xs text-danger">
          {(mutation.error as Error).message}
        </div>
      )}
      {lastRequest && !mutation.isError && (
        <div className="mt-2 text-xs text-muted">
          Queued · request_id: <code className="text-accent">{lastRequest}</code>
        </div>
      )}
    </section>
  );
}
