# Worldwide Quality of Life Map: build pipeline.
PY ?= python3

.PHONY: all fetch build serve clean global global-fetch global-ingest global-build renew locate

all: fetch build serve

fetch:            ## download every source into data/raw (skips files already present)
	cd pipeline && $(PY) fetch.py

build:            ## H3 substrate + layers -> data/processed and site/data
	cd pipeline && $(PY) build.py

serve:            ## open http://localhost:8000
	$(PY) -m http.server 8000 -d site

clean:            ## remove build outputs (keeps downloads)
	rm -rf data/processed site/data

# ---- WQL-003 global reference preview
global: global-fetch global-ingest global-build   ## whole globe: download, aggregate to H3, write site/global/data

global-fetch:     ## download every global source (about 5.5 GB) into data/raw
	cd pipeline && $(PY) global_fetch.py

global-ingest:    ## aggregate each source raster onto H3 res-5 cells (about 4 min)
	cd pipeline && $(PY) ingest.py

global-build:     ## finished values, display files, metadata, build version
	cd pipeline && $(PY) global_build.py

renew:            ## check every global source for upstream changes or newer releases
	cd pipeline && $(PY) renew.py

locate:           ## what is known at a place: make locate LL="-1.29 36.82"
	cd pipeline && $(PY) locate.py $(LL)
