"""
Record real Gemini responses for every call the demo batch makes.

    python -m app.tools.refresh_llm_cache
    python -m app.tools.refresh_llm_cache --all

Fills only missing keys by default. Existing recorded responses stay untouched
so the chain head does not move for unrelated reasons; `--all` clears the file
first, which is the deliberate act that follows a prompt rewrite.

Requires a real GEMINI_API_KEY. The recorded file is committed, so this needs
running once - after that, reviewers reproduce the demo with no key at all.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Must be set before app.config or app.database are imported: DEMO_MODE gates
# whether the cache is allowed to make live calls, and the engine is built at
# import time from DATABASE_URL.
os.environ["DEMO_MODE"] = "false"
CACHE_DB = Path(__file__).resolve().parents[2] / "recoveros_cache_build.db"
os.environ["DATABASE_URL"] = f"sqlite:///{CACHE_DB.as_posix()}"


async def build() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all", action="store_true",
        help="discard existing entries and re-record everything",
    )
    args = parser.parse_args()

    from app import llm_cache
    from app.config import GEMINI_API_KEY
    from app.database import Base, engine, SessionLocal
    from app.models import install_append_only_triggers
    import app.recovery_simulator as simulator

    if not GEMINI_API_KEY or "XXXX" in GEMINI_API_KEY:
        print("GEMINI_API_KEY is unset or a placeholder.")
        print("Set a real key in backend/.env, then run this again.")
        return 1

    if args.all:
        llm_cache._STORE = {}
        llm_cache.save()
        print("Cleared the existing cache - every response will be re-recorded.")

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(CACHE_DB) + suffix)
        if candidate.exists():
            candidate.unlink()
    Base.metadata.create_all(bind=engine)
    install_append_only_triggers(engine)

    original_sleep = simulator.asyncio.sleep

    async def no_sleep(_delay):
        return None

    simulator.asyncio.sleep = no_sleep
    db = SessionLocal()
    try:
        await simulator.run_batch_simulation(db, "batch_cache_build")
    finally:
        simulator.asyncio.sleep = original_sleep
        db.close()
        engine.dispose()

    llm_cache.save()
    stats = llm_cache.stats()
    print()
    print(f"Recorded {stats['writes']} new responses "
          f"({stats['hits']} already present).")
    print(f"Cache: {llm_cache.CACHE_PATH}")
    print()
    print("Read the recorded responses before committing them. The file ships")
    print("as evidence, so anything wrong in it is wrong in the submission.")

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(CACHE_DB) + suffix)
        if candidate.exists():
            candidate.unlink()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(build()))
