#!/usr/bin/env python3
"""Explicit, staging-only maintenance command for expired replay dispatch leases.

Expired dispatches are moved to RECONCILIATION_REQUIRED, never automatically replayed.
This command mutates staging state and requires --execute as an explicit opt-in.
"""
from __future__ import annotations
import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform the staging maintenance RPC")
    parser.add_argument("--cutoff-seconds", type=int, default=120, help="lease grace period, 30..86400 seconds")
    args = parser.parse_args(argv)
    env = os.getenv("APP_ENV", "").strip().lower()
    if not args.execute:
        print("NO-OP: pass --execute to reconcile expired staging replay leases")
        return 0
    if env != "staging":
        print("BLOCKED: APP_ENV must be explicitly set to staging", file=sys.stderr)
        return 2
    if not 30 <= args.cutoff_seconds <= 86400:
        print("BLOCKED: cutoff must be between 30 and 86400 seconds", file=sys.stderr)
        return 2
    try:
        from app.repositories.supabase_exceptions import SupabaseOperationalExceptionStore
        count = SupabaseOperationalExceptionStore().reconcile_expired_replays(cutoff_seconds=args.cutoff_seconds)
    except Exception:
        # Avoid printing configuration, SQL, network, or provider details.
        print("FAILED: expired replay reconciliation did not complete", file=sys.stderr)
        return 1
    print(f"PASS: {count} expired replay lease(s) moved to reconciliation; none were re-dispatched")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
