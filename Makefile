.PHONY: download
download:
	python3 favicon_download.py --output favicon/ico

.PHONY: png
png:
	python3 favicon_png.py --input favicon/ico --output favicon/png

.PHONY: prune
prune:
	python3 favicon_prune.py --favicon-dir favicon/ico --png-dir favicon/png

.PHONY: favicon
favicon: download png prune

.PHONY: gstatic
gstatic:
	python3 gstatic_download.py

.PHONY: all
all: favicon gstatic
