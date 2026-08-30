"""
Advance live recoveries that are due for their next step.

    python -m app.tools.run_tick                 # dry run - reports, writes nothing
    python -m app.tools.run_tick --execute       # acts

Dry run is the default and that is deliberate. This is the one tool in the
repository that can send a real customer a real Payment Link, so the safe
invocation has to be the short one and the dangerous one has to be typed out.

`--database-url` exists so the loop can be proven end to end against a copy of
a database without touching the original, which is the only honest way to
rehearse a step that spends money.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import argparse
import asyncio
import os
import sys

RULE = "=" * 72
THIN = "-" * 72


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_tick",
        description="Advance live recoveries that are due for their next step.",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually act. Without this the tool reports and writes nothing.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Report only (default).",
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL, e.g. to run against a copy of the database.",
    )
    return parser.parse_args(argv)


def render(result: dict) -> str:
    lines = [
        RULE,
        "  RecoverOS - Recovery Tick",
        THIN,
        f"  Mode              : {'DRY RUN (nothing written)' if result['dry_run'] else 'EXECUTE'}",
        f"  Now               : {result['now']}",
        f"  Follow-up window  : {result['follow_up_after_minutes']} minutes",
        f"  Open live records : {result['considered']}",
        THIN,
    ]

    if result["due"]:
        lines.append(f"  DUE ({len(result['due'])})")
        for payment_id in result["due"]:
            lines.append(f"    {payment_id}")
    else:
        lines.append("  DUE: none")

    if result["skipped"]:
        lines.append("")
        lines.append(f"  SKIPPED ({len(result['skipped'])})")
        for row in result["skipped"]:
            lines.append(f"    {row['payment_id']}  {row['reason']}")
            lines.append(f"      {row['detail']}")

    if result["advanced"]:
        lines.append("")
        lines.append(f"  ADVANCED ({len(result['advanced'])})")
        for row in result["advanced"]:
            detail = row.get("reason_code") or row.get("action")
            channel = f" via {row['channel']}" if row.get("channel") else ""
            lines.append(
                f"    {row['payment_id']}  {row['action']}{channel} "
                f"-> {row['recovery_state']}  [{detail}]"
            )

    if result["failed"]:
        lines.append("")
        lines.append(f"  FAILED ({len(result['failed'])})")
        for row in result["failed"]:
            lines.append(f"    {row['payment_id']}  {row['error']}")

    lines.append(THIN)
    if result["dry_run"]:
        lines.append("  Nothing was written and nothing was sent.")
        lines.append("  Re-run with --execute to act on the records listed as DUE.")
    lines.append(RULE)
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    dry_run = not args.execute

    if args.database_url:
        # Must precede the app.database import: the engine is built at import
        # time from DATABASE_URL.
        os.environ["DATABASE_URL"] = args.database_url

    from app.database import SessionLocal
    from app.recovery_tick import advance_open_recoveries

    if not dry_run:
        print(RULE)
        print("  EXECUTE mode. This may create real Razorpay Payment Links and")
        print("  spend real money against live records. Ctrl-C now if that is")
        print("  not what you meant.")
        print(RULE)

    db = SessionLocal()
    try:
        result = asyncio.run(advance_open_recoveries(db, dry_run=dry_run))
    finally:
        db.close()

    print(render(result))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
