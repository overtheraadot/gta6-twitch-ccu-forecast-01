"""GTA VI Twitch CCU forecaster (make.fun gta6-twitch-ccu-forecast-01, Account A).

Model: comparables-weighted log-ratio shape.
  * Every past launch in the case's `comparables` gives a release-day curve
    of log(viewers_h / viewers_1), h = 1..24.
  * Only "rolling-unlock" comparables are used for the shape: a launch whose
    noon viewers are more than ~4.5x its hour-1 print (log-ratio at hour 12
    above 1.5) had its hour 1 before its real unlock, so its curve is a
    different animal; GTA VI unlocks at midnight local, rolling, so those
    are dropped (with a fallback to the full pool if too few remain).
  * Each remaining launch is weighted by similarity to the target:
    a Gaussian kernel on log hour-1 viewers (launch size, bandwidth 1.5)
    times a wide Gaussian kernel on the log pre-release-to-hour-1 ratio
    (bandwidth 2.0, target ratio clamped into the pool's observed range,
    so GTA VI's extreme pre-release jump cannot hijack the weights).
  * Per hour, a kernel-weighted local-linear fit of the log-ratio on
    log hour-1 size gives the median shape (this both centres the shape on
    launches of the target's size and extrapolates the size trend when the
    target is bigger than every comparable).  The quantile spread is the
    weighted interquartile range of the fit residuals at that hour,
    converted to a robust sigma and widened by SPREAD_MULT, so the band
    widens with h exactly as the cross-launch dispersion does.
  * Everything is anchored to the case's hour-1 print: q = p1 * exp(lr).

Standard library only, no network, deterministic (fixed sort order, no
randomness, no wall-clock use).  Reads every *.in in the input directory
and writes one *.out per case.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

BW_H1 = 1.5        # kernel bandwidth on log hour-1 viewers
BW_PRE = 2.0       # kernel bandwidth on log(pre24 / hour1)
SPREAD_MULT = 1.0  # residual-based sigma, unscaled: LOO on big launches
                   # gives 90% coverage 0.904 at 1.0 (0.930 at 1.1, too wide;
                   # 1.25 over-covers at 0.961 and costs pinball)
ROLL_CAP = 1.5     # a comparable is rolling-like if log-ratio at hour 12 <= this
MIN_POOL = 8       # fall back to the full pool below this many rolling launches
RIDGE = 1e-3


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def weighted_quantile(pairs, tau):
    """Weighted quantile of (value, weight) pairs; pairs need not be sorted."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = tau * total
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= target:
            return value
    return ordered[-1][0]


def extract_curve(comp):
    """Release-day hourly viewers (24 numbers, hour 1..24) or None.

    A comparable is usable only if every release-day hour has a positive
    point; the GTA VI pre-release comparable has no release day yet, so
    it drops out here on its own.
    """
    day_start = parse_ts(comp["day_start"])
    by_hour = {}
    for point in comp.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        by_hour[parse_ts(point["from"])] = float(viewers)
    hours = [by_hour.get(day_start + timedelta(hours=i)) for i in range(24)]
    if any(v is None for v in hours):
        return None
    return hours


def pre24_mean(comp):
    """Mean viewers in the 24 h before the launch's day_start, or None."""
    day_start = parse_ts(comp["day_start"])
    values = []
    for point in comp.get("hourly") or []:
        at = parse_ts(point["from"])
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        if day_start - timedelta(days=1) <= at < day_start:
            values.append(float(viewers))
    if not values:
        return None
    return sum(values) / len(values)


def case_pre24_mean(case):
    """Mean of the target case's history_hourly in the 24 h before day_start."""
    day_start = parse_ts(case["day_start"])
    values = []
    for point in case.get("history_hourly") or []:
        at = parse_ts(point["from"])
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        if day_start - timedelta(days=1) <= at < day_start:
            values.append(float(viewers))
    if not values:
        return None
    return sum(values) / len(values)


def build_pool(case):
    """Comparable launches as (log hour-1, log pre-ratio, log-ratio curve)."""
    pool = []
    for comp in case.get("comparables") or []:
        hours = extract_curve(comp)
        if hours is None:
            continue
        hour1 = hours[0]
        pre = pre24_mean(comp)
        log_pre = math.log(pre / hour1) if pre else None
        log_ratio = [math.log(v / hour1) for v in hours]
        pool.append({"name": comp.get("name", "?"), "log_h1": math.log(hour1),
                     "log_pre": log_pre, "log_ratio": log_ratio})
    pool.sort(key=lambda c: c["name"])
    return pool


def similarity_weights(target_log_h1, target_log_pre, pool):
    """Kernel weights of each pool launch against the target.

    The pre-release ratio is clamped into the pool's observed range first:
    the target (GTA VI) sits far outside it, and an unclamped distance
    would hand the whole weight to the single most extreme comparable.
    """
    known_pre = [c["log_pre"] for c in pool if c["log_pre"] is not None]
    if known_pre and target_log_pre is not None:
        lo, hi = min(known_pre), max(known_pre)
        target_log_pre = min(max(target_log_pre, lo), hi)
        pool_pre_median = sorted(known_pre)[len(known_pre) // 2]
    else:
        pool_pre_median = 0.0
    weights = []
    for comp in pool:
        d_h1 = (comp["log_h1"] - target_log_h1) / BW_H1
        pre = comp["log_pre"] if comp["log_pre"] is not None else pool_pre_median
        if target_log_pre is None:
            d_pre = 0.0
        else:
            d_pre = (pre - target_log_pre) / BW_PRE
        weights.append(math.exp(-0.5 * (d_h1 * d_h1 + d_pre * d_pre)))
    return weights


def forecast_log_quantiles(target_log_h1, target_log_pre, pool):
    """{hour: [5 log-quantiles of viewers_h / viewers_1]} for hours 2..24."""
    # Rolling-unlock pool: drop launches whose hour 1 predates their unlock.
    rolling = [c for c in pool if c["log_ratio"][11] <= ROLL_CAP]
    use = rolling if len(rolling) >= MIN_POOL else pool
    weights = similarity_weights(target_log_h1, target_log_pre, use)

    out = {}
    for h in range(1, 24):  # index 1..23 == hours 2..24
        xs = [c["log_h1"] - target_log_h1 for c in use]
        ys = [c["log_ratio"][h] for c in use]
        total_w = sum(weights)
        mean_x = sum(w * x for w, x in zip(weights, xs)) / total_w
        mean_y = sum(w * y for w, y in zip(weights, ys)) / total_w
        sxx = sum(w * (x - mean_x) ** 2 for w, x in zip(weights, xs)) + RIDGE
        sxy = sum(w * (x - mean_x) * (y - mean_y)
                  for w, x, y in zip(weights, xs, ys))
        slope = sxy / sxx
        median = mean_y - slope * mean_x  # fitted value at the target's size
        residuals = [(y - (median + slope * x), w)
                     for x, y, w in zip(xs, ys, weights)]
        q25 = weighted_quantile(residuals, 0.25)
        q75 = weighted_quantile(residuals, 0.75)
        sigma = (q75 - q25) / 1.349 if q75 > q25 else 0.15
        out[h + 1] = [median + z * sigma * SPREAD_MULT for z in Z]
    return out


def forecast_case(case):
    known = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if known is not None and known.get("viewers"):
        p1 = max(1.0, float(known["viewers"]))
    else:
        # No hour-1 print: fall back to the last pre-checkpoint hourly mean.
        hourly = case.get("history_hourly") or []
        p1 = max(1.0, float(hourly[-1]["viewers"])) if hourly else 1.0
    pre = case_pre24_mean(case)
    target_log_pre = math.log(pre / p1) if pre else None
    pool = build_pool(case)
    if not pool:
        raise ValueError("no usable comparables in case")
    log_q = forecast_log_quantiles(math.log(p1), target_log_pre, pool)
    rows = []
    for row in case["forecast"]:
        h = row["hour"]
        qs = [p1 * math.exp(v) for v in log_q[h]]
        # Enforce the output contract: finite, > 0, <= 1e9, non-decreasing.
        clean = []
        prev = 0.0
        for q in qs:
            q = min(max(q, 1.0), 1e9)
            if not math.isfinite(q):
                q = p1
            q = max(q, prev)
            clean.append(round(q, 2))
            prev = q
        rows.append({"hour": h, "q": clean})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
