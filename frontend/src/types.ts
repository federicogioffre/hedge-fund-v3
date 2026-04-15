export type Health = {
  status: string;
  version: string;
  model_version: string;
  data_version: string;
  timestamp: string;
};

export type LivePosition = {
  ticker: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number | null;
  market_value: number | null;
  cost_basis: number;
  realized_pnl: number;
  unrealized_pnl: number | null;
  trading_mode: string;
};

export type FundPortfolio = {
  mode: "live" | "target";
  trading_mode?: string;
  cash?: number;
  equity?: number;
  total_market_value?: number;
  total_cost_basis?: number;
  total_realized_pnl?: number;
  total_unrealized_pnl?: number;
  peak_equity?: number;
  drawdown_pct?: number;
  daily_pnl?: number;
  position_count?: number;
  positions?: LivePosition[];
  trading_halted?: boolean;
  halt_reason?: string | null;
  initial_capital?: number;
  model_version?: string;
  timestamp?: string;
};

export type RankingEntry = {
  rank: number;
  ticker: string;
  overall_score: number | null;
  blended_score: number | null;
  confidence: number | null;
  conviction: number | null;
  risk_score: number | null;
  momentum: number | null;
  acceleration: number | null;
  recommendation: string | null;
  model_version: string | null;
  analyzed_at: string | null;
};

export type RankingResponse = {
  ranking: RankingEntry[];
  count: number;
  model_version: string;
  timestamp: string;
};

export type AnalyzeResponse = {
  request_id: string;
  ticker: string;
  status: string;
  message: string;
};

export type ExecutedOrder = {
  ticker: string;
  side: "buy" | "sell";
  size: number;
  notional: number;
  order?: Record<string, unknown>;
  dry_run?: boolean;
};

export type SkippedOrder = {
  ticker: string;
  reason: string;
  guard?: string;
  delta_pct?: number;
  side?: string;
  notional?: number;
};

export type RebalanceResponse = {
  status: string;
  trading_mode?: string;
  capital_base?: number;
  target_portfolio?: {
    positions: Array<{
      ticker: string;
      size_pct: number;
      allocation: number;
      score: number;
    }>;
    total_allocated_pct: number;
    cash_pct: number;
  };
  executed: ExecutedOrder[];
  skipped: SkippedOrder[];
  executed_count: number;
  skipped_count: number;
  fund_state: FundPortfolio;
  dry_run: boolean;
  timestamp: string;
  message?: string;
};

export type PnLResponse = {
  trading_mode: string;
  equity: number;
  cash: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  daily_pnl: number;
  drawdown_pct: number;
  peak_equity: number;
  live_positions: LivePosition[];
  positions: Array<{
    id: number;
    ticker: string;
    pnl: number;
    pnl_pct: number;
    created_at: string;
  }>;
  count: number;
  timestamp: string;
};
