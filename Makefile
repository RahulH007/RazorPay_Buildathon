
# RecoverOS — verification entry points.
#
# Every command in the README maps to a target here, so a reviewer can check a
# claim without reading the source first.

PY ?= venv/Scripts/python.exe
BACKEND := backend

.PHONY: help install demo verify-ledger tamper-demo measure test api web clean

help:
	@echo "RecoverOS"
	@echo ""
	@echo "  make install        Install backend dependencies"
	@echo "  make demo           Seeded batch. Prints the numbers quoted in the README."
	@echo "  make verify-ledger  Walk the hash chain; exits non-zero if broken."
	@echo "  make tamper-demo    Edit a cost in the database and watch it get caught."
	@echo "  make measure        Incremental-lift measurement with a 95% CI."
	@echo "  make test           Full test suite."
	@echo "  make api            Run the API on :8000"
	@echo "  make web            Run the dashboard on :5173"

install:
	$(PY) -m pip install -r $(BACKEND)/requirements.txt

demo:
	cd $(BACKEND) && ../$(PY) -m app.tools.run_demo

verify-ledger:
	cd $(BACKEND) && ../$(PY) -m app.tools.verify_ledger

tamper-demo:
	cd $(BACKEND) && ../$(PY) -m app.tools.tamper_demo

measure:
	cd $(BACKEND) && ../$(PY) -m app.tools.run_measurement --contacts 2000 --seeds 10 --out ../results/lift_analysis.md

test:
	cd $(BACKEND) && ../$(PY) -m pytest tests/ -q

api:
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --port 8000

web:
	cd frontend && npm run dev

clean:
	rm -f $(BACKEND)/recoveros.db $(BACKEND)/recoveros.db-wal $(BACKEND)/recoveros.db-shm
	@echo "Database removed. It regenerates on the next run."
