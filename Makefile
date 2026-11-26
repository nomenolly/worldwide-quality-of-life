# Worldwide Quality of Life Map: build pipeline.
PY ?= python3

.PHONY: all fetch build serve clean

all: fetch build serve

fetch:            ## download every source into data/raw (skips files already present)
	cd pipeline && $(PY) fetch.py

build:            ## H3 substrate + layers -> data/processed and site/data
	cd pipeline && $(PY) build.py

serve:            ## open http://localhost:8000
	$(PY) -m http.server 8000 -d site

clean:            ## remove build outputs (keeps downloads)
	rm -rf data/processed site/data
