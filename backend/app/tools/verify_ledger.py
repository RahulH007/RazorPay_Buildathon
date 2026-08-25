"""
Verify the RecoverOS ledger from the command line.

    python -m app.tools.verify_ledger

Exits 0 when the chain is intact, 1 when it is not, so it can gate CI.
"""

import os
from pathlib import Path

# Operate on the same throwaway database the demo receipt builds, unless the
# caller overrides DATABASE_URL to inspect a different ledger.
if not os.environ.get("DATABASE_URL"):
    _demo = Path(__file__).resolve().parents[2] / "recoveros_demo.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{_demo.as_posix()}"

import sys

from app import ledger
from app.database import SessionLocal, engine
from app.models import AuditTrailEntry
from sqlalchemy import func


def main() -> int:
    db = SessionLocal()
    try:
        print("=" * 68)
        print("  RecoverOS - Ledger Verification")
        print("=" * 68)
        print(f"  Database        : {engine.url}")
        print(f"  Preimage version: {ledger.PREIMAGE_VERSION}")
        print(f"  Genesis prev    : {ledger.GENESIS_PREV_HASH[:32]}...")
        print("-" * 68)

        result = ledger.verify_chain(db)
        total_cost_paise = db.query(func.sum(AuditTrailEntry.cost_paise)).scalar() or 0

        print(f"  Entries checked : {result.entries_checked}")
        print(f"  Total spend     : Rs {total_cost_paise / 100:,.2f} ({total_cost_paise} paise)")

        if result.valid:
            print(f"  Head hash       : {result.head_hash or '(empty ledger)'}")
            print("-" * 68)
            print("  RESULT: VALID - every entry hashes correctly, links to its")
            print("          predecessor, and no sequence number is missing.")
            print("=" * 68)
            return 0

        print(f"  Broken at seq   : {result.first_broken_sequence}")
        print("-" * 68)
        print("  RESULT: TAMPERED")
        print(f"  {result.reason}")
        print("=" * 68)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
