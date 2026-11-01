# 5. Show farmers measured rainfall; keep the forecast behind a gate

**Decision.** Farmer channels report observed season rainfall against each commune's own history.
The shortfall forecast stays experimental, on the analyst dashboard only, until it passes an
automatic promotion gate: the lower end of the 90% interval on Brier skill must exceed zero.

**Why.** The note proposes forecasting shortfalls and validating against IPC outcomes. Commune-level
IPC history is not openly available, so we tested rainfall shortfall instead: after the first
month of a season, will the rest fall in the driest fifth of that commune's history?

Walk-forward backtests on 2006-2026, with whole seasons resampled for the interval, found no
reliable skill. Logistic regression scored 0.002 (90% interval -0.077 to 0.084) and gradient
boosting -0.059. Trying whole-season totals and excess rain gave no target whose interval cleared
zero. We then stopped looking, because further variations would only risk a lucky result.

**Consequence.** The note's forecasting goal is not met yet, and we say so. CHIRPS plus ENSO and the
Indian Ocean Dipole is not enough at this lead time. Better inputs to try next are seasonal
forecasts from IGEBU or ICPAC, NDVI and soil moisture, and yield or IPC labels from partners.
