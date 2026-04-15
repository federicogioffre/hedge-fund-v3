import type {
  AnalyzeResponse,
  FundPortfolio,
  Health,
  PnLResponse,
  RankingResponse,
  RebalanceResponse,
} from "../types";

// Use relative /api paths — Vite proxies these to the FastAPI container
const BASE = "/api/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  health: () => req<Health>("/health"),
  portfolio: () => req<FundPortfolio>("/portfolio"),
  ranking: (limit = 25) => req<RankingResponse>(`/ranking?limit=${limit}`),
  pnl: () => req<PnLResponse>("/pnl"),
  analyze: (ticker: string, asset_type: "equity" | "crypto" = "equity") =>
    req<AnalyzeResponse>("/analyze", {
      method: "POST",
      body: JSON.stringify({ ticker, asset_type }),
    }),
  rebalance: (dry_run: boolean) =>
    req<RebalanceResponse>("/rebalance", {
      method: "POST",
      body: JSON.stringify({ dry_run }),
    }),
  halt: (reason: string) =>
    req<{ status: string }>("/risk/halt", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  resume: () =>
    req<{ status: string }>("/risk/resume", { method: "POST" }),
};
