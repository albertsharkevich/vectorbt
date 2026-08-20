def apply_slippage(price, side, config):
    """Worsen a fill price to simulate slippage: buys fill higher, sells fill lower."""
    adj = price * (config.slippage_bps / 10_000)
    return price + adj if side == "buy" else price - adj


def sell_regulatory_fees(proceeds, shares, config):
    """SEC + FINRA pass-through fees charged on the sell side of a round trip."""
    sec_fee = proceeds * config.sec_fee_rate
    finra_taf = min(shares * config.finra_taf_per_share, config.finra_taf_cap)
    return sec_fee + finra_taf


def buy_commission(shares, config):
    return shares * config.commission_per_share
