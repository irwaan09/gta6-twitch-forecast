# How the forecast works

`main.py` is the whole entry: one Python 3.13 program, standard library
only, no network, deterministic. It reads one case file (`*.in`) and
writes one forecast file (`*.out`) with five quantiles (0.05, 0.25, 0.5,
0.75, 0.95) of Twitch concurrent viewers in the Grand Theft Auto VI
category for each hour 2..24 of release day, 2026-11-19 (UTC).

## The idea

GTA VI unlocks at midnight local time, rolling country by country, on
consoles only, with no early access. Past launches that unlocked the same
way trace a recognisable UTC-day shape:

- hours 2-4 dip (Europe asleep, the US not yet unlocked),
- hours 6 and 9 lift as the US east coast, then west coast, unlock,
- hours 19-23 peak in the European evening as the US afternoon joins in,
  roughly 2-2.5x the first hour,
- hour 24 eases off.

Launches that unlocked everywhere at one global instant (a simultaneous
PC/Steam unlock, a 14:00Z global drop) trace a very different shape, so
they are left out. Early-access launches are left out too: their
release-day curve is contaminated by viewers from days earlier.

## The model

For each comparable launch in the case file, take its release-day hourly
counts and divide every hour by that launch's own hour-1 count. Work in
log space. For hour `h`:

- `median_h = p1 * exp(median of the log ratios at h)`, where `p1` is
  this case's hour-1 print;
- `q_tau(h) = median_h * exp(z_tau * sigma_h)`, where `z_tau` is the
  standard normal quantile at each scored level and `sigma_h` is the
  spread of the log ratios across the pool at that hour
  (interquartile range / 1.349, times 1.5, floored at 0.30).

The pool is the comparables tagged "comparable" that are console-only
(no PC/Stadia version) or unlocked at rolling midnight local time —
14 launches in the practice cases, more in the final case, where the
four practice launches join the pool. If the pool ever drops below 5
launches it widens to all "comparable" launches, then to every launch
with a complete release day.

## Validation

The constants 1.5 (spread multiplier) and 0.30 (spread floor) were
picked by leave-one-out scoring on the kit's own comparables: forecast
each launch's release day from the other launches in the pool and score
the mean pinball loss on the log scale, the contest's own metric.

- This model: mean leave-one-out loss about **0.22** (90% coverage
  about 0.95).
- The house persistence baseline on the same launches: about **0.34**
  (the house reports about 0.387 on the practice cases).

Including simultaneous-unlock launches in the pool roughly triples the
loss (about 0.91), which is why the pool filter matters. A wider spread
than 1.5x costs loss at every hour; a narrower one pays for every hour
outside the band.

## Robustness

- No usable comparables: falls back to the persistence forecast
  (hour 1's print, random-walk spread widening over the day).
- Any unexpected case shape (missing hour-1 print, odd levels, a
  broken comparable): still writes a valid persistence forecast, so a
  case is never left invalid. An invalid case scores as if every
  quantile equalled hour 1's print and takes no prize.
- Two runs on the same case write byte-identical output; a run over
  the four practice cases takes under a second.
