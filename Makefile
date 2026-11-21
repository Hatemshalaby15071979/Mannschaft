SHELL := bash
export PYTHONPATH := src

.PHONY: check lint test validate render assemble serve corpus-suggest clean \
	dist-core dist-full dist-check serve-bg stop-bg logo

check: lint test

lint:
	# --no-cache: the project lives on a mount where ruff's atomic cache
	# rename fails with EINVAL. Linting is fast enough without it.
	ruff check --no-cache src tests

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

# ---- brand ---------------------------------------------------------------

logo:
	python3 tools/make_logo.py

# ---- packaging (V6) -------------------------------------------------------

dist-core:
	python3 tools/package.py --kind core --out dist/v5-core.zip

dist-full:
	python3 tools/package.py --kind full --out dist/v5-full.zip

dist-check:
	python3 tools/dist_check.py

# ---- local service (V6) ---------------------------------------------------

serve-bg:
	./tools/serve_detached.sh

stop-bg:
	./tools/stop_server.sh

clean:
	rm -rf .pytest_cache .ruff_cache dist
