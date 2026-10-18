VENV := backend/.venv
PY := $(VENV)/bin/python

.PHONY: setup dev backend frontend test build report audit vision-data vision-train

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -e "backend[dev]"
	cd frontend && pnpm install

# Backend on :8000 and frontend on :5173 (open http://localhost:5173).
dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && .venv/bin/uvicorn cbv.main:app --reload --reload-dir cbv --port 8000

frontend:
	cd frontend && pnpm dev

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && pnpm lint && pnpm test && pnpm build

# Accuracy report for one book: make report BOOK=samples/mybook.pdf
report:
	$(PY) scripts/report.py "$(BOOK)"

audit:
	$(PY) scripts/diagram_audit.py "$(BOOK)"

# Rebuild a diagram classifier (needs `pip install -e "backend[train]"` and two typed-diagram books).
# By default the one that knows square marks; `make vision-data vision-train MARKS=--no-marks
# MODEL=pieces.onnx` rebuilds the other.
WOODPECKER ?= samples/the-woodpecker-method-by-axel-smith-amp-hans-tikkanen.pdf
POLGAR ?= samples/5334 Problems, Combinations, and Games - Laszlo Polgar.pdf
MARKS ?=
MODEL ?= pieces-marks.onnx
vision-data:
	$(PY) backend/tools/vision_dataset.py --out .data/squares.npz --woodpecker "$(WOODPECKER)" --polgar "$(POLGAR)" $(MARKS)

vision-train:
	$(PY) backend/tools/vision_train.py --data .data/squares.npz --out backend/cbv/vision/$(MODEL)
