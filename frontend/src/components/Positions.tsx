import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const n = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: d });

export function Positions() {
  const { data } = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    refetchInterval: 5000,
  });

  const positions =
    data?.mode === "live" ? data.positions ?? [] : [];

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">
          POSITIONS
        </h2>
        <span className="text-xs text-muted">{positions.length} open</span>
      </div>

      {positions.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted">
          No open positions. Run <code>/rebalance</code> after analyzing some tickers.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-right">Avg Entry</th>
                <th className="px-4 py-2 text-right">Current</th>
                <th className="px-4 py-2 text-right">Market Value</th>
                <th className="px-4 py-2 text-right">Unrealized PnL</th>
                <th className="px-4 py-2 text-right">Realized PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const upnl = p.unrealized_pnl ?? 0;
                const tone = upnl >= 0 ? "text-accent" : "text-danger";
                return (
                  <tr
                    key={p.ticker}
                    className="border-t border-border hover:bg-bg/40"
                  >
                    <td className="px-4 py-2 font-semibold">{p.ticker}</td>
                    <td className="px-4 py-2 text-right">{n(p.quantity, 4)}</td>
                    <td className="px-4 py-2 text-right text-muted">
                      ${n(p.avg_entry_price)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      ${n(p.current_price)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      ${n(p.market_value, 0)}
                    </td>
                    <td className={`px-4 py-2 text-right ${tone}`}>
                      {upnl >= 0 ? "+" : ""}${n(upnl, 2)}
                    </td>
                    <td className="px-4 py-2 text-right text-muted">
                      ${n(p.realized_pnl, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
