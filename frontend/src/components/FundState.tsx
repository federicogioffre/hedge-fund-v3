import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const fmt = (n: number | undefined | null, decimals = 2) =>
  n == null ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: decimals });

const pct = (n: number | undefined | null) =>
  n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

function Card({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warn";
}) {
  const toneCls =
    tone === "positive"
      ? "text-accent"
      : tone === "negative"
      ? "text-danger"
      : tone === "warn"
      ? "text-warn"
      : "text-slate-200";

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function FundState() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    refetchInterval: 5000,
  });

  if (isLoading)
    return <div className="text-sm text-muted">Loading fund state…</div>;
  if (error)
    return (
      <div className="text-sm text-danger">
        Error loading fund state: {(error as Error).message}
      </div>
    );
  if (!data || data.mode !== "live") return null;

  const pnl = (data.total_realized_pnl ?? 0) + (data.total_unrealized_pnl ?? 0);
  const pnlTone = pnl >= 0 ? "positive" : "negative";
  const ddTone = (data.drawdown_pct ?? 0) > 5 ? "negative" : "neutral";
  const dailyTone =
    (data.daily_pnl ?? 0) >= 0 ? "positive" : "negative";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <Card
        label="Equity"
        value={`$${fmt(data.equity, 0)}`}
        sub={`start: $${fmt(data.initial_capital, 0)}`}
      />
      <Card
        label="Cash"
        value={`$${fmt(data.cash, 0)}`}
        sub={`positions: ${data.position_count ?? 0}`}
      />
      <Card
        label="Total PnL"
        value={`${pnl >= 0 ? "+" : ""}$${fmt(pnl, 0)}`}
        sub={
          <>
            realized ${fmt(data.total_realized_pnl, 0)} ·{" "}
            unrealized ${fmt(data.total_unrealized_pnl, 0)}
          </>
        }
        tone={pnlTone}
      />
      <Card
        label="Daily PnL"
        value={`${(data.daily_pnl ?? 0) >= 0 ? "+" : ""}$${fmt(
          data.daily_pnl,
          0
        )}`}
        tone={dailyTone}
      />
      <Card
        label="Drawdown"
        value={pct(data.drawdown_pct)}
        sub={`peak: $${fmt(data.peak_equity, 0)}`}
        tone={ddTone}
      />
    </div>
  );
}
