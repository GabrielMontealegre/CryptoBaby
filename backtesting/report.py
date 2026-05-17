"""
backtesting/report.py

Formats and saves backtest results.
Prints honest assessment to console.
Saves JSON report to disk.
Does NOT hide bad results.
"""

import json
import os
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger("backtest_report")


def print_report(results):
    if not results or "error" in results:
        print("\n❌ BACKTEST FAILED — No trades executed or data error.")
        print(f"   {results.get('error', 'Unknown error')}")
        return

    s = results["summary"]
    cfg = results["config"]

    print("\n" + "=" * 65)
    print("  BACKTEST RESULTS — HONEST ASSESSMENT")
    print("=" * 65)
    print(f"  Symbols    : {', '.join(cfg['symbols'])}")
    print(f"  Interval   : {cfg['interval']}")
    print(f"  Lookback   : {cfg['lookback_days']} days")
    print(f"  Balance    : ${cfg['starting_balance']:.2f} -> ${s['ending_balance']:.2f}")
    sign = '+' if s['total_return_pct'] >= 0 else ''
    print(f"  Return     : {sign}{s['total_return_pct']:.2f}%")
    print("-" * 65)
    print(f"  Trades     : {s['total_trades']}  (signals: {s['total_signals']}, rejected: {s['rejected_signals']})")
    print(f"  Win Rate   : {s['win_rate_pct']:.1f}%  ({s['wins']}W / {s['losses']}L)")
    print(f"  Avg Win    : ${s['avg_win_usd']:.2f}")
    print(f"  Avg Loss   : ${s['avg_loss_usd']:.2f}")
    print(f"  Best Trade : ${s['best_trade_usd']:.2f}")
    print(f"  Worst Trade: ${s['worst_trade_usd']:.2f}")
    print(f"  Max Drawdown: {s['max_drawdown_pct']:.2f}%")
    print(f"  Profit Factor: {s['profit_factor']}")
    print(f"  Total Fees : ${s['total_fees_usd']:.2f}")
    print("-" * 65)

    print("  BY SYMBOL:")
    for sym, d in results.get("by_symbol", {}).items():
        pnl_str = f"+${d['pnl_usd']:.2f}" if d['pnl_usd'] >= 0 else f"-${abs(d['pnl_usd']):.2f}"
        print(f"    {sym:<10} {d['trades']:>3} trades | {d['win_rate_pct']:>5.1f}% win | PnL: {pnl_str}")

    print("  EXIT REASONS:")
    for reason, count in results.get("exit_reasons", {}).items():
        print(f"    {reason:<20}: {count}")

    print("-" * 65)
    print("  VERDICT:")
    _print_verdict(s)
    print("=" * 65 + "\n")


def _print_verdict(s):
    issues = []
    positives = []

    if s["total_return_pct"] > 5:
        positives.append("OK Positive return over test period")
    elif s["total_return_pct"] > 0:
        issues.append("WARN Marginally positive - may not beat fees in live trading")
    else:
        issues.append("FAIL NEGATIVE RETURN - strategy lost money in this period")

    if s["win_rate_pct"] >= 55:
        positives.append("OK Win rate above 55% - acceptable for 2:1 R:R")
    elif s["win_rate_pct"] >= 45:
        issues.append("WARN Win rate 45-55% - borderline, needs more data")
    else:
        issues.append("FAIL Win rate below 45% - losing more often than winning")

    if s["profit_factor"] >= 1.5:
        positives.append("OK Profit factor >= 1.5 - strategy has edge")
    elif s["profit_factor"] >= 1.0:
        issues.append("WARN Profit factor 1.0-1.5 - small edge, fragile")
    else:
        issues.append("FAIL Profit factor < 1.0 - strategy destroys capital")

    if s["max_drawdown_pct"] <= 10:
        positives.append("OK Max drawdown <= 10% - acceptable risk")
    elif s["max_drawdown_pct"] <= 20:
        issues.append("WARN Max drawdown 10-20% - elevated risk")
    else:
        issues.append(f"FAIL Max drawdown {s['max_drawdown_pct']:.1f}% - too high")

    if s["total_trades"] < 10:
        issues.append("WARN Too few trades - results not statistically meaningful")
    elif s["total_trades"] < 30:
        issues.append("WARN Under 30 trades - extend lookback for confidence")

    for p in positives:
        print(f"    {p}")
    for i in issues:
        print(f"    {i}")

    if not positives and issues:
        print("    DO NOT proceed to live trading based on these results.")
    elif issues:
        print("    Fix issues above before considering live trading.")
    else:
        print("    Results acceptable - extend lookback before live trading.")


def save_report(results, output_dir="logs"):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"backtest_{ts}.json")
    with open(json_path, "w") as f:
        report_data = {k: v for k, v in results.items() if k != "equity_curve"}
        json.dump(report_data, f, indent=2, default=str)
    if results.get("equity_curve"):
        eq_path = os.path.join(output_dir, f"equity_curve_{ts}.json")
        with open(eq_path, "w") as f:
            json.dump(results["equity_curve"], f, default=str)
    log.info(f"Report saved to {json_path}")
    print(f"  Report saved: {json_path}")
    return json_path
