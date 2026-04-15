import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const recoColor = (reco: string | null) => {
  if (!reco) return "text-muted";
  if (reco.includes("strong_buy")) return "text-accent font-bold";
  if (reco.includes("buy")) return "text-accent";
  if (reco.includes("strong_sell")) return "text-danger font-bold";
  if (reco.includes("sell")) return "text-danger";
  return "text-muted";
};

const n = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toFixed(d);

export function Ranking() {
  const { data, isLoading } = useQuery({
    queryKey: ["ranking"],
    queryFn: () => api.ranking(25),
    refetchInterval: 8000,
  });

  const rows = data?.ranking ?? [];

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">
          RANKING
        </h2>
        <span className="text-xs text-muted">
          {isLoading ? "loading…" : `${rows.length} tickers`}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted">
          No analysis yet. Use the form below to analyze a ticker.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="px-4 py-2 text-left">#</th>
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-right">Score</th>
                <th className="px-4 py-2 text-right">Conf</th>
                <th className="px-4 py-2 text-right">Conviction</th>
                <th className="px-4 py-2 text-right">Risk</th>
                <th className="px-4 py-2 text-right">Momentum</th>
                <th className="px-4 py-2 text-right">Recommendation</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.ticker}
                  className="border-t border-border hover:bg-bg/40"
                >
                  <td className="px-4 py-2 text-muted">{r.rank}</td>
                  <td className="px-4 py-2 font-semibold">{r.ticker}</td>
                  <td className="px-4 py-2 text-right">
                    {n(r.overall_score, 2)}
                  </td>
                  <td className="px-4 py-2 text-right text-muted">
                    {n(r.confidence, 2)}
                  </td>
                  <td className="px-4 py-2 text-right text-accent">
                    {n(r.conviction, 2)}
                  </td>
                  <td className="px-4 py-2 text-right text-muted">
                    {n(r.risk_score, 2)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {r.momentum == null ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <span
                        className={
                          r.momentum > 0
                            ? "text-accent"
                            : r.momentum < 0
                            ? "text-danger"
                            : "text-muted"
                        }
                      >
                        {r.momentum > 0 ? "+" : ""}
                        {n(r.momentum, 3)}
                      </span>
                    )}
                  </td>
                  <td
                    className={`px-4 py-2 text-right ${recoColor(
                      r.recommendation
                    )}`}
                  >
                    {r.recommendation?.replace("_", " ") ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
