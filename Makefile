# Run targets one at a time; the download and silver build take a few minutes each.
# ARCHIVE is the path to MongoDB's sampledata.archive (used once, for the 2015 sample).

ARCHIVE ?= data/sampledata.archive
MONGO_URI ?= mongodb://localhost:27018/?directConnection=true
RUN = uv run storefronts

.PHONY: help up down ping restore download boundaries load-raw copy-sample silver link-sample \
        indexes nta link-switch profile status test lint gold exports dashboard notebooks

help: ## List available commands
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

up: ## Start MongoDB (Atlas local image) on port 27018
	docker compose up -d

down: ## Stop MongoDB (data volume is kept)
	docker compose down

ping: ## Check the database connection
	$(RUN) ping

restore: ## Restore sample_training from sampledata.archive (uses Docker if mongorestore is missing)
	@test -f "$(ARCHIVE)" || { echo "ARCHIVE not found: $(ARCHIVE)"; exit 1; }
	@if command -v mongorestore >/dev/null 2>&1; then \
		mongorestore --uri="$(MONGO_URI)" --drop --archive="$(ARCHIVE)" --nsInclude='sample_training.*'; \
	else \
		echo "mongorestore not on PATH; running it from the mongo:8.0 image"; \
		docker run --rm --network host -v "$(abspath $(ARCHIVE))":/sample.archive:ro mongo:8.0 \
			mongorestore --uri="$(MONGO_URI)" --drop --archive=/sample.archive --nsInclude='sample_training.*'; \
	fi

download: ## Download archive (since ARCHIVE_SINCE) and live inspections from NYC Open Data
	$(RUN) download all

boundaries: ## Download 2020 NTA neighborhood boundaries
	$(RUN) boundaries

load-raw: ## Load downloads into raw_archive and raw_live
	$(RUN) load-raw all

copy-sample: ## Copy the 2015 sample next to the city data
	$(RUN) copy-sample

silver: ## Build the unified, validated inspections collection
	$(RUN) build-silver all

link-sample: ## Flag archive rows that are in the 2015 sample
	$(RUN) link-sample

indexes: ## Create secondary indexes
	$(RUN) create-indexes

nta: ## Load 2020 NTA polygons and tag inspections by point in polygon (after silver)
	$(RUN) load-nta
	$(RUN) assign-nta

link-switch: ## Link businesses across the 2023 system switch (after silver)
	$(RUN) link-switch

profile: ## Write reports/data_quality.md
	$(RUN) profile

status: ## Show collection counts
	$(RUN) status

test: ## Unit tests, plus integration tests if MongoDB is reachable
	uv run pytest -q

lint: ## Ruff lint
	uv run ruff check .
	uv run ruff format --check .

gold: ## Rebuild visit_features and business_status; audit strictly earlier history
	OMP_NUM_THREADS=4 $(RUN) gold

exports: ## Export ten CSVs from gold and notebook results
	$(RUN) exports

dashboard: ## Build docs/index.html
	uv run python src/storefronts/dashboard.py

notebooks: ## Execute and save all four analysis notebooks in order
	OMP_NUM_THREADS=4 uv run jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=1800 notebooks/01_eda.ipynb notebooks/02_ground_truth.ipynb \
		notebooks/03_model.ipynb notebooks/04_ghost_count.ipynb
