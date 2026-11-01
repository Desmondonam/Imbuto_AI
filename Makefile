.PHONY: setup data train all test lint run traffic alerts notebooks
UV ?= uv

setup:      ## Install everything
	$(UV) sync

data:       ## Download open data and build bronze, silver, gold
	$(UV) run python -c "from imbuto.lakehouse.sources import fetch_all; fetch_all()"
	$(UV) run python scripts/fetch_training_data.py
	$(UV) run python -m imbuto.lakehouse.build

train:      ## Train models and write artifact bundles
	$(UV) run python -m imbuto.ml.train

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

run:        ## Serve on http://localhost:8000
	$(UV) run uvicorn imbuto.api.main:app --factory --host 0.0.0.0 --port 8000

traffic:    ## Send realistic traffic to a running server, then a drifted burst
	$(UV) run python scripts/simulate_traffic.py

alerts:     ## Queue SMS alerts for subscribers in very dry communes
	$(UV) run python -m imbuto.core.alerts

notebooks:  ## Re-execute all notebooks in place
	$(UV) run jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
