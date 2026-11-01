# 1. DuckDB and Parquet before Spark and Delta

**Decision.** Keep the note's bronze/silver/gold layers, built with Python, DuckDB and Parquet.

**Why.** Burundi's data at commune-month grain is megabytes, not terabytes. A Spark cluster would
cost money and operations effort that buy nothing at this size, and nobody in the room could run
it on a laptop.

**Consequence.** Layer contracts stay the same, so moving to Spark and Delta later changes the
engine, not the design. Move when data outgrows one machine or concurrent writers appear.
