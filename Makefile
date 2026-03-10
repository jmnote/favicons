.PHONY: download png prune

download:
	python3 download_favicon.py

png:
	python3 generate_png.py

prune:
	python3 prune_assets.py
