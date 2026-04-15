import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function Header() {
  const qc = useQueryClient();
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 10000,
  });
  const { data: portfolio } = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    refetchInterval: 5000,
  });

  const halt = useMutation({
    mutationFn: () => api.halt("manual_halt_from_ui"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }),
  });
  const resume = useMutation({
    mutationFn: () => api.resume(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }),
  });

  const isHalted = portfolio?.trading_halted;
  const mode = portfolio?.trading_mode ?? "paper";

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-bg/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="text-accent font-bold tracking-tight">
            ◆ Hedge Fund
          </div>
          <span className="rounded bg-border px-2 py-0.5 text-xs text-slate-300">
            v{health?.version ?? "…"}
          </span>
          <span className="rounded bg-border px-2 py-0.5 text-xs text-slate-300">
            {health?.model_version ?? "…"}
          </span>
          <span
            className={`rounded px-2 py-0.5 text-xs ${
              mode === "live"
                ? "bg-danger/20 text-danger"
                : "bg-accent/10 text-accent"
            }`}
          >
            {mode.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span
              className={`h-2 w-2 rounded-full ${
                health?.status === "healthy"
                  ? "bg-accent"
                  : "bg-danger"
              }`}
            />
            {health?.status ?? "unknown"}
          </div>

          {isHalted ? (
            <button
              onClick={() => resume.mutate()}
              disabled={resume.isPending}
              className="rounded border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/20"
            >
              {resume.isPending ? "…" : "▶ Resume Trading"}
            </button>
          ) : (
            <button
              onClick={() => halt.mutate()}
              disabled={halt.isPending}
              className="rounded border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs text-danger hover:bg-danger/20"
            >
              {halt.isPending ? "…" : "■ Halt Trading"}
            </button>
          )}
        </div>
      </div>
      {isHalted && (
        <div className="bg-danger/10 px-4 py-1.5 text-center text-xs text-danger">
          TRADING HALTED — {portfolio?.halt_reason ?? "manual"}
        </div>
      )}
    </header>
  );
}
