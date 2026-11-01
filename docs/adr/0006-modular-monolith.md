# 6. One deployable service

**Decision.** Run API, web and channels as one FastAPI service with clear internal modules and
SQLite storage. Rain outlooks are precomputed in batch.

**Why.** A small team must be able to run this on one cheap machine, possibly in-country. Separate
services would add network failure modes and operations work without any load to justify them.

**Consequence.** SQLite means one writer host. Move to Postgres when running multiple replicas.
Module boundaries make later extraction straightforward.
