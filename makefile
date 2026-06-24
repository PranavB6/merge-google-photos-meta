# Makefile
.PHONY: install test build publish clean

install:
	pip install -e ".[dev]"

test:
	pytest

clean:
	rm -rf dist/ *.egg-info/

build: clean test
	python -m build
	twine check dist/*

publish: build
	twine upload dist/*

publish-test: build
	twine upload --repository testpypi dist/*