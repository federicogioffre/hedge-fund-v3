from datetime import datetime

from app.version import MODEL_VERSION


def build_report_html(
    rankings: list[dict],
    fund_state: dict | None,
    positions: list[dict],
) -> str:
    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    ranking_rows = ""
    for i, r in enumerate(rankings, 1):
        score = r.get("overall_score")
        score_str = f"{score:.2f}" if score is not None else "-"
        conf = r.get("confidence")
        conf_str = f"{conf:.0%}" if conf is not None else "-"
        conv = r.get("conviction")
        conv_str = f"{conv:.3f}" if conv is not None else "-"
        rec = r.get("recommendation", "-")
        rec_color = _rec_color(rec)
        ranking_rows += (
            f"<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:center'>{i}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;font-weight:bold'>{r.get('ticker', '-')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:center'>{score_str}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:center'>{conf_str}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:center'>{conv_str}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:center;color:{rec_color}'>{rec}</td>"
            f"</tr>"
        )

    position_rows = ""
    if positions:
        for p in positions:
            pnl = p.get("unrealized_pnl", 0) or 0
            pnl_color = "#00d4aa" if pnl >= 0 else "#ff4757"
            qty = p.get("quantity", 0)
            entry = p.get("avg_entry_price", 0)
            current = p.get("current_price", 0)
            position_rows += (
                f"<tr>"
                f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;font-weight:bold'>{p.get('ticker', '-')}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:right'>{qty:.2f}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:right'>${entry:,.2f}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:right'>${current:,.2f}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #2a2a3e;text-align:right;color:{pnl_color}'>${pnl:,.2f}</td>"
                f"</tr>"
            )

    positions_section = ""
    if position_rows:
        positions_section = f"""
        <h2 style="color:#00d4aa;font-size:18px;margin:30px 0 15px 0;border-bottom:1px solid #2a2a3e;padding-bottom:8px">
            Open Positions
        </h2>
        <table style="width:100%;border-collapse:collapse;color:#e0e0e0;font-size:14px">
            <thead>
                <tr style="color:#888;font-size:12px;text-transform:uppercase">
                    <th style="padding:8px;text-align:left;border-bottom:2px solid #2a2a3e">Ticker</th>
                    <th style="padding:8px;text-align:right;border-bottom:2px solid #2a2a3e">Qty</th>
                    <th style="padding:8px;text-align:right;border-bottom:2px solid #2a2a3e">Entry</th>
                    <th style="padding:8px;text-align:right;border-bottom:2px solid #2a2a3e">Current</th>
                    <th style="padding:8px;text-align:right;border-bottom:2px solid #2a2a3e">Unreal. P&L</th>
                </tr>
            </thead>
            <tbody>{position_rows}</tbody>
        </table>
        """

    fund_section = ""
    if fund_state:
        equity = fund_state.get("equity", 0)
        cash = fund_state.get("cash", 0)
        daily_pnl = fund_state.get("daily_pnl", 0)
        drawdown = fund_state.get("drawdown_pct", 0)
        halted = fund_state.get("trading_halted", False)
        daily_color = "#00d4aa" if daily_pnl >= 0 else "#ff4757"
        halted_badge = (
            "<span style='background:#ff4757;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px'>HALTED</span>"
            if halted else
            "<span style='background:#00d4aa;color:#000;padding:2px 8px;border-radius:4px;font-size:12px'>ACTIVE</span>"
        )
        fund_section = f"""
        <h2 style="color:#00d4aa;font-size:18px;margin:20px 0 15px 0;border-bottom:1px solid #2a2a3e;padding-bottom:8px">
            Portfolio Snapshot {halted_badge}
        </h2>
        <table style="width:100%;border-collapse:collapse;color:#e0e0e0;font-size:14px">
            <tr>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;color:#888">Equity</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;text-align:right;font-weight:bold;font-size:18px">${equity:,.2f}</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;color:#888">Cash</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;text-align:right;font-weight:bold">${cash:,.2f}</td>
            </tr>
            <tr>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;color:#888">Daily P&L</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;text-align:right;font-weight:bold;color:{daily_color}">${daily_pnl:,.2f}</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;color:#888">Drawdown</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;text-align:right;font-weight:bold">{drawdown:.2f}%</td>
            </tr>
        </table>
        """

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#111122;font-family:'Segoe UI',Arial,sans-serif">
    <div style="max-width:640px;margin:0 auto;padding:20px">
        <div style="background:#1a1a2e;border-radius:12px;padding:30px;border:1px solid #2a2a3e">
            <h1 style="color:#00d4aa;font-size:22px;margin:0 0 5px 0">Hedge Fund V7</h1>
            <p style="color:#888;font-size:14px;margin:0 0 25px 0">Daily Report &mdash; {date_str}</p>

            {fund_section}

            <h2 style="color:#00d4aa;font-size:18px;margin:30px 0 15px 0;border-bottom:1px solid #2a2a3e;padding-bottom:8px">
                Ranking ({len(rankings)} tickers)
            </h2>
            <table style="width:100%;border-collapse:collapse;color:#e0e0e0;font-size:14px">
                <thead>
                    <tr style="color:#888;font-size:12px;text-transform:uppercase">
                        <th style="padding:8px;text-align:center;border-bottom:2px solid #2a2a3e">#</th>
                        <th style="padding:8px;text-align:left;border-bottom:2px solid #2a2a3e">Ticker</th>
                        <th style="padding:8px;text-align:center;border-bottom:2px solid #2a2a3e">Score</th>
                        <th style="padding:8px;text-align:center;border-bottom:2px solid #2a2a3e">Conf.</th>
                        <th style="padding:8px;text-align:center;border-bottom:2px solid #2a2a3e">Conv.</th>
                        <th style="padding:8px;text-align:center;border-bottom:2px solid #2a2a3e">Rec.</th>
                    </tr>
                </thead>
                <tbody>{ranking_rows}</tbody>
            </table>

            {positions_section}

            <p style="color:#555;font-size:11px;margin:30px 0 0 0;text-align:center">
                Model {MODEL_VERSION} &bull; Generated {date_str}
            </p>
        </div>
    </div>
</body>
</html>"""


def _rec_color(rec: str) -> str:
    rec = (rec or "").lower()
    if rec in ("strong_buy", "buy"):
        return "#00d4aa"
    if rec in ("strong_sell", "sell"):
        return "#ff4757"
    return "#e0e0e0"
