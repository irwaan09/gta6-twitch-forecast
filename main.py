"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Method: a launch-day shape learned from past big launches, anchored on
this launch's own first hour.

GTA VI unlocks at midnight local time, rolling country by country, on
consoles only, with no early access. Past launches that unlocked the same
way trace a recognisable UTC-day shape: a dip in the small hours (Europe
asleep, the US not yet unlocked), a lift when the US east coast unlocks
(hour 6) and the west coast follows (hour 9), and a peak in the European
evening (hours 19-23) as the US afternoon joins in. Launches that
unlocked everywhere at one global instant trace a very different shape,
so they are left out: on leave-one-out scoring over the kit's own
comparables they roughly triple the loss.

For each comparable launch we take its release-day hourly counts, divide
every hour by that launch's hour-1 count, and work in log space. The
forecast for hour h is then:

    median_h = p1 * exp(median of log ratios at h)
    q_tau(h) = median_h * exp(z_tau * sigma_h)

where p1 is this case's hour-1 print, z_tau is the standard normal
quantile at each scored level, and sigma_h is the spread of the log
ratios across the pool at that hour (interquartile range / 1.349,
inflated by 1.5 and floored at 0.30). The pool is the comparables that
are console-only or unlocked at rolling midnight local time, excluding
early-access-contaminated and weak analogues. The constants 1.5 and
0.30 were picked by leave-one-out pinball-loss scoring over the
comparables themselves (mean loss about 0.22, versus about 0.34 for the
persistence baseline on the same launches).

The program is deterministic, standard library only, and never touches
the network: everything it needs is inside the case file. If the case
carries no usable comparables it falls back to the persistence forecast
(hour 1's print with a widening random-walk spread), and if anything
else goes wrong for a case it still writes a valid persistence forecast
for it, so a case is never left invalid.

Run locally with:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
The grader runs `python3 -P -s /bot/main.py` with /input and /output.
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a
# module shipped beside this file would still import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# Spread calibration, picked by leave-one-out scoring on the comparables.
SPREAD_MULTIPLIER = 1.5
SPREAD_FLOOR = 0.30
# Fallback persistence spread (log units per square-root hour).
PERSISTENCE_SIGMA = 0.15

TIER_RE = re.compile(r"Tier:\s*([a-z-]+)")


def round2(x):
    """x rounded to 2 decimals, half up, as the house baseline rounds it.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def median(values):
    """Median of a non-empty list of floats (deterministic)."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def quartile(values, p):
    """Linear-interpolation quantile of a non-empty sorted list."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    pos = p * (n - 1)
    lo = int(pos)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[min(lo + 1, n - 1)] * frac


def parse_time(text):
    """An ISO-8601 UTC timestamp into a datetime (naive, UTC)."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def release_day_series(comp):
    """A comparable's 24 release-day hourly viewer counts, hours 1..24.

    Returns None when any of the 24 hours is missing (a sparse or
    non-launch series, such as the target game's own pre-release history).
    """
    try:
        day_start = parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_hour = {}
    for row in comp.get("hourly") or []:
        try:
            hour = int((parse_time(row["from"]) - day_start).total_seconds() // 3600) + 1
            viewers = row["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= hour <= 24 and isinstance(viewers, (int, float)):
            by_hour[hour] = viewers
    if len(by_hour) < 24:
        return None
    return [by_hour[h] for h in range(1, 25)]


def is_rolling_midnight(comp):
    """True when the launch unlocked at midnight local time, rolling."""
    unlock = (comp.get("unlock") or "").lower()
    return "midnight local" in unlock or "rolling" in unlock


def is_console_only(comp):
    """True when the launch had no PC (or Stadia) version to unlock at once."""
    platforms = comp.get("platforms") or ""
    return "PC" not in platforms and "Stadia" not in platforms


def tier_of(comp):
    """The kit's tier tag for a comparable, or '' when it carries none."""
    match = TIER_RE.search(comp.get("unlock") or "")
    return match.group(1) if match else ""


def pool_series(case):
    """Release-day series of the comparables that resemble this launch.

    Preferred pool: tier "comparable" launches that are console-only or
    rolled out at midnight local time. Falls back to every tier
    "comparable" launch, then to every launch with a complete release
    day, so the forecast never ends up with an empty pool.
    """
    series = []
    for comp in case.get("comparables") or []:
        s = release_day_series(comp)
        if s is not None:
            series.append((comp, s))
    if not series:
        return []
    preferred = [s for comp, s in series
                 if tier_of(comp) == "comparable"
                 and (is_console_only(comp) or is_rolling_midnight(comp))]
    if len(preferred) >= 5:
        return preferred
    comparable = [s for comp, s in series if tier_of(comp) == "comparable"]
    if len(comparable) >= 5:
        return comparable
    return [s for _, s in series]


def shape_from_pool(pool):
    """Per-hour (median log ratio, IQR of log ratios) against hour 1.

    Each pool launch contributes one log ratio per hour: how that hour's
    viewers compare with the launch's own hour-1 count. The median is
    the shape; the interquartile range is the honest spread.
    """
    shape = {}
    for h in range(2, 25):
        ratios = []
        for s in pool:
            first = max(s[0], 1)
            ratios.append(math.log(max(s[h - 1], 1)) - math.log(first))
        shape[h] = (median(ratios),
                    quartile(ratios, 0.75) - quartile(ratios, 0.25))
    return shape


def shape_quantiles(shape, p1, h):
    """The five quantiles for hour h from the learned shape."""
    med_log_ratio, iqr = shape[h]
    sigma = max(SPREAD_MULTIPLIER * iqr / 1.349, SPREAD_FLOOR)
    centre = p1 * math.exp(med_log_ratio)
    return [round2(centre * math.exp(z * sigma)) for z in Z]


def persistence_quantiles(p1, h):
    """The house baseline's forecast: hour 1's print, widening spread."""
    return [round2(p1 * math.exp(z * PERSISTENCE_SIGMA * math.sqrt(h - 1)))
            for z in Z]


def forecast_case(case, name):
    """One case's 23 forecast rows, hours 2..24."""
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1, first["viewers"])
    hours = [row["hour"] for row in case.get("forecast") or []]
    if not hours:
        hours = list(range(2, 25))
    pool = pool_series(case)
    if pool:
        shape = shape_from_pool(pool)
        rows = [{"hour": h, "q": shape_quantiles(shape, p1, h)} for h in hours]
    else:
        rows = [{"hour": h, "q": persistence_quantiles(p1, h)} for h in hours]
    return {"hours": rows}


def safe_forecast_case(case, name):
    """A forecast that is valid even when the case is not as expected.

    Anything unexpected (a missing hour-1 print, odd levels, a broken
    comparable) falls back to persistence from hour 1's print, or from
    1 viewer when even that is missing, so the case still scores instead
    of going invalid.
    """
    try:
        return forecast_case(case, name)
    except Exception:
        try:
            first = next((k for k in case.get("known") or []
                          if k.get("hour") == 1), None)
            p1 = max(1, first["viewers"]) if first else 1
        except Exception:
            p1 = 1
        hours = [row["hour"] for row in case.get("forecast") or []]
        if not hours:
            hours = list(range(2, 25))
        return {"hours": [{"hour": h, "q": persistence_quantiles(p1, h)}
                          for h in hours]}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = safe_forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
