# 5. Predict rainfall shortfall, not IPC phase

**Decision.** Mid-season, predict whether the rest of the season will fall in the driest fifth of
that commune's history. Validate by holding out whole recent years.

**Why.** The note proposes validating against IPC outcomes, but commune-level IPC history is not
openly available, and a handful of national events cannot train a model. Rainfall gives a real,
measured label for every commune and season since 1981.

**Consequence.** The output is a *rainfall* risk, not a food-security forecast, and must be
described that way. Replace or extend the target when partners share IPC or yield data.
