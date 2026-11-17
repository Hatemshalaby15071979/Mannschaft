SHELL := bash
export PYTHONPATH := src

.PHONY: check lint test validate render assemble serve corpus-suggest clean

check: lint test

lint:
	ruff check src tests

test:
	python3 -m pytest

validate:
	python3 -m v5 validate --all

render:
	@test -n "$(ID)" || (echo "usage: make render ID=A2-01" && exit 1)
	python3 -m v5 render $(ID)

assemble:
	@test -n "$(ID)" || (echo "usage: make assemble ID=A2-01" && exit 1)
	python3 -m v5 assemble $(ID)

serve:
	python3 -m v5 serve

corpus-suggest:
	python3 -m v5 corpus suggest --level $(LEVEL) --situation $(SITUATION)

clean:
	rm -rf .pytest_cache .ruff_cache
