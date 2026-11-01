# Human review needed before any real farmer sees this

Nothing below may go live without the named reviewer. Until then the app runs in demo mode and
shows a banner saying the content is unreviewed.

| What | Files | Reviewer | Why |
| --- | --- | --- | --- |
| Kirundi text | `locale/rn.json`, `knowledge/` | Native Kirundi speaker, ideally a farmer-facing one | Machine-drafted, not checked by any speaker |
| Agronomy content | `knowledge/` | Agronomist (ISABU, ministry or field partner) | Written from general knowledge, unapproved |
| Disease model | `artifacts/crop_health/` | Plant pathologist, and a Burundian test set | Trained on Ugandan images, beans only |
| Rain outlook wording | `src/imbuto/core/outlook.py` | IGEBU or a meteorologist | Could conflict with official forecasts |
| Data protection | `docs/ARCHITECTURE.md` | Legal counsel | Alignment with the 2026 law is unverified |
