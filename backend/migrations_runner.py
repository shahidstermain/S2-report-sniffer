#!/usr/bin/env python3
"""
Migration runner for S2-report-sniffer.
Applies pending migrations in sequence order.

Usage:
    python backend/migrations_runner.py up [--migration ID] [--dry-run]
    python backend/migrations_runner.py status
    python backend/migrations_runner.py history
"""
import sys
import os
import argparse
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

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
        from pymongo import MongoClient
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        print(f"[migrate] Connected to MongoDB at {mongo_url}")
        return client
    except Exception as e:
        print(f"[migrate] ERROR: Cannot connect to MongoDB at {mongo_url}: {e}")
        print("[migrate] Cannot run migrations without MongoDB connectivity.")
        sys.exit(1)


def get_applied_migrations(client) -> dict:
    meta = client.get_database().migrations_meta
    try:
        record = meta.find_one({"_id": "migration_registry"})
        return record.get("applied", {}) if record else {}
    except Exception:
        return {}


def record_migration(client, migration_id: str):
    meta = client.get_database().migrations_meta
    meta.update_one(
        {"_id": "migration_registry"},
        {
            "$set": {
                f"applied.{migration_id}": {
                    "applied_at": __import__("datetime").datetime.utcnow().isoformat(),
                    "action": "applied",
                }
            }
        },
        upsert=True,
    )


def get_pending_migrations(client) -> list:
    applied = get_applied_migrations(client)
    pending = [
        mid for mid in sorted(MIGRATION_REGISTRY)
        if mid not in applied
    ]
    return pending


def run_migration(client, migration_id: str, dry_run: bool = False) -> bool:
    migration = MIGRATION_REGISTRY.get(migration_id)
    if not migration:
        print(f"[migrate] Unknown migration: {migration_id}")
        return False

    mod_path = os.path.join(MIGRATIONS_DIR, migration["name"])
    if not os.path.exists(mod_path):
        print(f"[migrate] Migration file not found: {mod_path}")
        return False

    spec = importlib.util.spec_from_file_location(f"mig_{migration_id}", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "up"):
        print(f"[migrate] Migration {migration_id} has no up() function.")
        return False

    print(f"[migrate] Applying migration {migration_id}: {migration['description']}")
    if dry_run:
        print(f"[migrate] DRY RUN — would apply migration {migration_id}")
        return True

    try:
        mod.up(client)
        record_migration(client, migration_id)
        print(f"[migrate] Migration {migration_id} applied successfully.")
        return True
    except Exception as e:
        print(f"[migrate] ERROR applying migration {migration_id}: {e}")
        return False


def apply_all_pending(client, dry_run: bool = False):
    pending = get_pending_migrations(client)
    if not pending:
        print("[migrate] No pending migrations.")
        return

    print(f"[migrate] {len(pending)} pending migration(s): {pending}")
    for mid in pending:
        ok = run_migration(client, mid, dry_run=dry_run)
        if not ok:
            print(f"[migrate] Stopping at migration {mid} due to error.")
            break


def show_status(client):
    applied = get_applied_migrations(client)
    print("\n=== Migration Status ===")
    print(f"{'ID':<6} {'Status':<15} Description")
    print("-" * 60)
    for mid, info in sorted(MIGRATION_REGISTRY.items()):
        if mid in applied:
            status = f"APPLIED ({applied[mid].get('applied_at', '')})"
        else:
            status = "PENDING"
        print(f"{mid:<6} {status:<15} {info['description']}")


def show_history(client):
    applied = get_applied_migrations(client)
    history = sorted(applied.items(), key=lambda x: x[1].get("applied_at", ""), reverse=True)
    print("\n=== Migration History ===")
    if not history:
        print("No migrations applied yet.")
        return
    for mid, info in history:
        print(f"  {mid}: applied at {info.get('applied_at')}")


def main():
    parser = argparse.ArgumentParser(description="Migration runner for S2-report-sniffer")
    sub = parser.add_subparsers(dest="command")

    up_cmd = sub.add_parser("up", help="Apply pending migrations")
    up_cmd.add_argument("--migration", help="Apply a specific migration ID only")
    up_cmd.add_argument("--dry-run", action="store_true", help="Show what would be applied without applying")

    sub.add_parser("status", help="Show migration status")
    sub.add_parser("history", help="Show migration history")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    client = get_mongo_client()

    if args.command == "up":
        if args.migration:
            run_migration(client, args.migration, dry_run=args.dry_run)
        else:
            apply_all_pending(client, dry_run=args.dry_run)
    elif args.command == "status":
        show_status(client)
    elif args.command == "history":
        show_history(client)

    client.close()


if __name__ == "__main__":
    main()
