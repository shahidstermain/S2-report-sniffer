#!/usr/bin/env python3
"""
Rollback runner for S2-report-sniffer.
Rolls back applied migrations in reverse order.

Usage:
    python backend/rollback_runner.py down [--steps N] [--force]
    python backend/rollback_runner.py status
    python backend/rollback_runner.py history
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__))

MIGRATION_REGISTRY = {
    "001": {
        "name": "001_add_recommendations_metadata.py",
        "description": "Add SuperChecker metadata fields to recommendations",
        "is_applied": False,
    },
}


def get_mongo_client():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from pymongo import MongoClient
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        print(f"[rollback] Connected to MongoDB at {mongo_url}")
        return client
    except Exception as e:
        print(f"[rollback] ERROR: Cannot connect to MongoDB at {mongo_url}: {e}")
        print("[rollback] Cannot run migrations without MongoDB connectivity.")
        sys.exit(1)


def get_applied_migrations(client) -> dict:
    meta = client.get_database().migrations_meta
    try:
        record = meta.find_one({"_id": "migration_registry"})
        if record:
            return record.get("applied", {})
        return {}
    except Exception:
        return {}


def record_migration(client, migration_id: str, action: str):
    meta = client.get_database().migrations_meta
    meta.update_one(
        {"_id": "migration_registry"},
        {
            "$set": {
                f"applied.{migration_id}": {
                    "applied_at": __import__("datetime").datetime.utcnow().isoformat(),
                    "action": action,
                }
            }
        },
        upsert=True,
    )


def rollback_migration(client, migration_id: str, force: bool = False):
    migration = MIGRATION_REGISTRY.get(migration_id)
    if not migration:
        print(f"[rollback] Unknown migration: {migration_id}")
        return False

    mod_path = os.path.join(MIGRATIONS_DIR, migration["name"])
    if not os.path.exists(mod_path):
        print(f"[rollback] Migration file not found: {mod_path}")
        return False

    import importlib.util
    spec = importlib.util.spec_from_file_location(f"mig_{migration_id}", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "down"):
        print(f"[rollback] Migration {migration_id} has no down() function.")
        return False

    try:
        if force:
            confirm = input(
                f"[rollback] FORCE flag set — this will execute the down migration {migration_id}. Continue? [y/N]: "
            )
            if confirm.lower() != "y":
                print("[rollback] Aborted.")
                return False
        mod.down(client)
        record_migration(client, migration_id, "rolled_back")
        print(f"[rollback] Successfully rolled back migration {migration_id}")
        return True
    except Exception as e:
        print(f"[rollback] ERROR during rollback of {migration_id}: {e}")
        return False


def rollback_last_n(client, n: int = 1, force: bool = False):
    applied = get_applied_migrations(client)
    migration_ids = sorted(applied.keys(), reverse=True)
    to_rollback = migration_ids[:n]

    if not to_rollback:
        print("[rollback] No applied migrations to roll back.")
        return

    print(f"[rollback] Rolling back {len(to_rollback)} migration(s): {to_rollback}")
    for mid in to_rollback:
        ok = rollback_migration(client, mid, force=force)
        if not ok:
            print(f"[rollback] Stopping rollback at {mid} due to error.")
            break


def show_status(client):
    applied = get_applied_migrations(client)
    print("\n=== Migration Status ===")
    print(f"{'ID':<6} {'Applied At':<30} {'Action':<15} Description")
    print("-" * 75)
    for mid, info in sorted(MIGRATION_REGISTRY.items()):
        applied_info = applied.get(mid)
        if applied_info:
            print(f"{mid:<6} {applied_info.get('applied_at',''):<30} {applied_info.get('action',''):<15} {info['description']}")
        else:
            print(f"{mid:<6} {'[NOT APPLIED]':<30} {'-':<15} {info['description']}")


def show_history(client):
    applied = get_applied_migrations(client)
    history = sorted(applied.items(), key=lambda x: x[1].get("applied_at", ""), reverse=True)
    print("\n=== Migration History ===")
    if not history:
        print("No migrations applied yet.")
        return
    for mid, info in history:
        print(f"  {mid}: {info.get('action')} at {info.get('applied_at')}")


def main():
    parser = argparse.ArgumentParser(description="Rollback runner for S2-report-sniffer migrations")
    sub = parser.add_subparsers(dest="command")

    down_cmd = sub.add_parser("down", help="Rollback the last N migrations")
    down_cmd.add_argument("--steps", type=int, default=1, help="Number of migrations to roll back (default: 1)")
    down_cmd.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    sub.add_parser("status", help="Show migration status")
    sub.add_parser("history", help="Show migration history")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    client = get_mongo_client()

    if args.command == "down":
        rollback_last_n(client, n=args.steps, force=args.force)
    elif args.command == "status":
        show_status(client)
    elif args.command == "history":
        show_history(client)

    client.close()


if __name__ == "__main__":
    main()
