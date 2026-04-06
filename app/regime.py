from typing import Any
from app.data_bundle import DataBundle
from app.logging import get_logger

logger = get_logger(__name__)


def detect_regime(bundle: DataBundle) -> dict[str, Any]:
    """
    Detect market regime and volatility regime from market data.

    Market regime:
        change_pct > 2  → "bull"
        change_pct < -2 → "bear"
        else            → "sideways"

    Volatility regime:
        volatility > 30 → "high_vol"
        else            → "low_vol"
    """
    market = bundle.market
    change_pct = market.get("change_pct", 0)
    volatility = market.get("volatility", abs(change_pct))

    # Market regime
    if change_pct > 2:
        market_regime = "bull"
    elif change_pct < -2:
        market_regime = "bear"
    else:
        market_regime = "sideways"

    # Volatility regime
    if volatility > 30:
        vol_regime = "high_vol"
    else:
        vol_regime = "low_vol"

    result = {
        "market_regime": market_regime,
        "vol_regime": vol_regime,
        "change_pct": change_pct,
        "volatility": volatility,
    }

    logger.info(
        "regime_detected",
        ticker=bundle.ticker,
        market_regime=market_regime,
        vol_regime=vol_regime,
    )

    return result
