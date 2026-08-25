"""
Demonstrate that the ledger detects tampering.

    python -m app.tools.tamper_demo

The scenario is the realistic one: someone with direct database access edits a
recovery cost to hide what was spent. The script does exactly that — opening
the SQLite file directly, outside the ORM — then re-verifies.

It restores the original value afterwards so the demo can be run repeatedly.
Nothing here is part of the application; it exists to prove a claim.
"""

import os
from pathlib import Path

# Operate on the same throwaway database the demo receipt builds, unless the
# caller overrides DATABASE_URL to inspect a different ledger.
if not os.environ.get("DATABASE_URL"):
    _demo = Path(__file__).resolve().parents[2] / "recoveros_demo.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{_demo.as_posix()}"

import sqlite3
import sys
from pathlib import Path

from app import ledger
from app.database import SessionLocal, engine
from app.models import (
    AuditTrailEntry,
    drop_append_only_triggers,
    install_append_only_triggers,
)


def _db_path() -> Path:
    url = str(engine.url)
    return Path(url.replace("sqlite:///", "")).resolve()


def _rule(char: str = "-") -> None:
    print(char * 68)


def main() -> int:
    db = SessionLocal()
    try:
        before = ledger.verify_chain(db)
        if before.entries_checked == 0:
            print("Ledger is empty. Run a batch first: python -m app.tools.run_demo")
            return 2

        target = (
            db.query(AuditTrailEntry)
            .filter(AuditTrailEntry.cost_paise > 0)
            .order_by(AuditTrailEntry.sequence_no)
            .first()
        ) or db.query(AuditTrailEntry).order_by(AuditTrailEntry.sequence_no).first()

        sequence_no = target.sequence_no
        original_cost = target.cost_paise
        original_details = target.details
        payment_id = target.payment_id
        action = target.action
    finally:
        db.close()

    print("=" * 68)
    print("  RecoverOS - Tamper Detection Demo")
    print("=" * 68)
    print(f"  Chain before : VALID, {before.entries_checked} entries")
    print(f"  Head hash    : {before.head_hash}")
    _rule()
    print("  Target entry")
    print(f"    sequence   : {sequence_no}")
    print(f"    payment    : {payment_id}")
    print(f"    action     : {action}")
    print(f"    cost       : {original_cost} paise (Rs {original_cost / 100:,.2f})")
    _rule()

    path = _db_path()

    # Step 1: the append-only triggers must be defeated first. A real attacker
    # with file access could do this; the point is that it does not help them.
    print("  [1] Dropping append-only triggers (simulating full DB access)...")
    drop_append_only_triggers(engine)

    print("  [2] Editing the cost directly via sqlite3, bypassing the ORM...")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE audit_trail_entries SET cost_paise = 0 WHERE sequence_no = ?",
            (sequence_no,),
        )
        connection.commit()
    finally:
        connection.close()
    print(f"      cost {original_cost} paise -> 0 paise (spend hidden)")

    print("  [3] Re-verifying the chain...")
    _rule()

    db = SessionLocal()
    try:
        after = ledger.verify_chain(db)
    finally:
        db.close()

    if after.valid:
        print("  UNEXPECTED: tampering was NOT detected. This is a bug.")
        exit_code = 1
    else:
        print("  RESULT: TAMPERING DETECTED")
        print(f"    broken at sequence : {after.first_broken_sequence}")
        print(f"    entries verified   : {after.entries_checked} (before the break)")
        print(f"    reason             : {after.reason}")
        exit_code = 0

    _rule()
    print("  [4] Restoring the original value and triggers...")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE audit_trail_entries SET cost_paise = ?, details = ? WHERE sequence_no = ?",
            (original_cost, original_details, sequence_no),
        )
        connection.commit()
    finally:
        connection.close()
    install_append_only_triggers(engine)

    db = SessionLocal()
    try:
        restored = ledger.verify_chain(db)
    finally:
        db.close()

    print(f"      chain restored: {'VALID' if restored.valid else 'STILL BROKEN'}")
    print("=" * 68)
    print("  Note: the tamper only succeeded because the triggers were dropped")
    print("  first. Without that, SQLite itself rejects the UPDATE - and even")
    print("  with full file access, the edit is still detected by the hash.")
    print("=" * 68)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
