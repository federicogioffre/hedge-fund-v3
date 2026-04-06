import math
import hashlib
import random
from typing import Any
from app.portfolio_engine import construct_portfolio
from app.logging import get_logger

logger = get_logger(__name__)


def run_backtest_v2(
    tickers: list[str],
    days: int = 30,
    capital: float = 100_000.0,
) -> dict[str, Any]:
    """
    Backtesting engine V2.

    For each day:
        1. Generate simulated ranking for each ticker
        2. Construct portfolio
        3. Simulate daily return

    Returns:
        total_return, sharpe_ratio, max_drawdown, win_rate
    """
    daily_returns = []
    portfolio_value = capital
    peak_value = capital
    max_drawdown = 0.0
    winning_days = 0

    for day in range(days):
        # 1. Generate simulated ranking for the day
        rankings = []
        for ticker in tickers:
            seed = int(
                hashlib.md5(f"{ticker}:{day}".encode()).hexdigest()[:8], 16
            )
            rng = random.Random(seed)

            score = round(2.5 + rng.random() * 2.5, 2)  # 2.5-5.0
            confidence = round(0.4 + rng.random() * 0.5, 2)  # 0.4-0.9
            risk_score = round(0.1 + rng.random() * 0.5, 2)  # 0.1-0.6
            conviction = round(score * confidence * (1 - risk_score), 2)

            if score >= 4.0 and conviction >= 1.5:
                rec = "strong_buy"
            elif score >= 3.5:
                rec = "buy"
            elif score >= 2.5:
                rec = "hold"
            else:
                rec = "sell"

            rankings.append({
                "ticker": ticker,
                "overall_score": score,
                "confidence": confidence,
                "risk_score": risk_score,
                "conviction": conviction,
                "recommendation": rec,
            })

        # 2. Construct portfolio
        portfolio = construct_portfolio(rankings, portfolio_value)

        # 3. Simulate daily return for each position
        daily_pnl = 0.0
        for pos in portfolio["positions"]:
            seed = int(
                hashlib.md5(
                    f"{pos['ticker']}:return:{day}".encode()
                ).hexdigest()[:8],
                16,
            )
            rng = random.Random(seed)
            # Daily return: slight positive bias, scaled by score
            base_return = (rng.gauss(0.001, 0.02))
            score_adj = (pos["score"] - 3.0) * 0.002
            daily_ticker_return = base_return + score_adj
            daily_pnl += pos["allocation"] * daily_ticker_return

        portfolio_value += daily_pnl
        daily_return = daily_pnl / (portfolio_value - daily_pnl) if (portfolio_value - daily_pnl) > 0 else 0
        daily_returns.append(daily_return)

        if daily_return > 0:
            winning_days += 1

        if portfolio_value > peak_value:
            peak_value = portfolio_value
        drawdown = (peak_value - portfolio_value) / peak_value if peak_value > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Calculate metrics
    total_return = (portfolio_value - capital) / capital

    if daily_returns:
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(
            daily_returns
        )
        std_return = math.sqrt(variance) if variance > 0 else 0.0001
        sharpe_ratio = (mean_return / std_return) * math.sqrt(252)  # annualized
    else:
        mean_return = 0
        std_return = 0
        sharpe_ratio = 0

    win_rate = winning_days / days if days > 0 else 0

    result = {
        "total_return": round(total_return * 100, 3),
        "total_return_abs": round(portfolio_value - capital, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "max_drawdown": round(max_drawdown * 100, 3),
        "win_rate": round(win_rate * 100, 2),
        "final_value": round(portfolio_value, 2),
        "initial_capital": capital,
        "days": days,
        "tickers": tickers,
        "daily_returns_count": len(daily_returns),
    }

    logger.info(
        "backtest_completed",
        total_return=result["total_return"],
        sharpe=result["sharpe_ratio"],
        max_dd=result["max_drawdown"],
        win_rate=result["win_rate"],
    )

    return result
