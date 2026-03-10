.PHONY: download gstatic png prune

download:
	python3 download_favicon.py

gstatic:
	python3 download_gstatic.py

png:
	python3 generate_png.py

prune:
	python3 prune_assets.py
