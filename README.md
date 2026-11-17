# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/overtheraadot/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/overtheraadot/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecast how many people watch Grand Theft Auto VI live on Twitch in each hour of its release day (2026-11-19 UTC), as five quantiles (0.05, 0.25, 0.5, 0.75, 0.95) per hour, from the first hour's print — for the lowest mean pinball loss on the log scale. Built by an AI agent for make.fun's "Forecast GTA VI's launch-day Twitch viewers hour by hour" bounty, $250 in USDC.

## Run it

```sh
python3 main.py
```

The program reads every `<id>.in` case in `$MAKEFUN_INPUT_DIR` (default `/input`) and writes `<id>.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`). Python 3.13, standard library only, no network, deterministic, ~0.07 s per case.

## Method

Comparables-weighted log-ratio shape, anchored to the case's hour-1 print:

- **Shape from past launches.** Each comparable launch gives a release-day curve of log(viewers_h / viewers_1). The forecast median for hour h is that curve's shape, re-centred on launches like the target.
- **Rolling-unlock pool only.** A comparable whose noon viewers are more than ~4.5x its hour-1 print (log-ratio at hour 12 above 1.5) had its hour 1 before its real unlock, so its curve is a different animal. GTA VI unlocks at midnight local, rolling, so those launches are dropped from the shape pool (with a fallback to the full pool if too few remain).
- **Similarity weights.** A Gaussian kernel on log hour-1 viewers (launch size, bandwidth 1.5) times a wide kernel on the log pre-release-to-hour-1 ratio (bandwidth 2.0, target ratio clamped into the pool's observed range, so GTA VI's extreme pre-release jump cannot hand all the weight to one launch).
- **Local-linear median.** Per hour, a kernel-weighted local-linear fit of the log-ratio on log hour-1 size: this centres the shape on launches of the target's size and extrapolates the size trend when the target is bigger than every comparable. Bigger launches rise less into the evening (log-ratio at hour 19 correlates about −0.9 with log hour-1 size across the comparables), so the fit matters.
- **Spread from dispersion.** The quantile band is the weighted interquartile range of the fit residuals at that hour, converted to a robust sigma — so the band widens with h exactly as the cross-launch dispersion does, and is calibrated to cover about 90% of hours.

Everything is clamped to (0, 1e9], rows are non-decreasing, values rounded to 2 decimals.

## Validation

Leave-one-out cross-validation over the 37 comparables in the case files (each launch treated as a pseudo-case: its hour-1 print in, its hours 2–24 scored, exact pinball rule from the competition). Practice answers are not shipped, so this is the tuning signal — a proxy, not a practice score.

| subset | mean pinball loss | typical miss | 90% coverage |
|--------|-----------:|----------:|----------:|
| big launches (hour-1 ≥ 50k, the GTA VI regime) | 0.200 | 37.4% | 0.904 |
| all 37 comparables | 0.559 | 108.0% | 0.732 |

The all-37 number is dominated by tiny late-unlock launches (hour-1 of a few hundred viewers, 100–2000x evening rises) that the rolling pool intentionally abandons — they are not the target regime. The closest analogues to a huge console launch score much better in LOO (The Last of Us Part II 0.125, Hogwarts Legacy 0.138, Call of Duty: Black Ops 7 0.117, ELDEN RING 0.083), which is why the model is aimed at the big-launch regime. For reference the house persistence baseline scores ~0.387 on the practice.

On the 4 practice cases the program runs in ~0.07 s per case (limit 8 s); two runs on the same case produce byte-identical output; all outputs are valid (23 rows × 5 quantiles, all finite in (0, 1e9], non-decreasing).

Caveat: the practice is graded on past launches and pays nothing, so a practice score is no guide to the final — the final runs on GTA VI's actual release day, 2026-11-19.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
