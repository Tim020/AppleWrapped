#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path
from app.tracker import collect_command, report_command, stats_command
from app.logging_config import configure_logging, logger
from app.config import CouchbaseConfig
from app.database.backend_manager import BackendManager
from app.database.sync_manager import SyncManager


def main():

    # Determine default database path (script directory)
    default_db_path = Path(__file__).resolve().parent / "apple_music_history.db"

    parser = argparse.ArgumentParser(description='Apple Music History Tracker')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity (-v=INFO, -vv=DEBUG)')
    parser.add_argument('--db-path', type=Path, default=default_db_path,
                        help=f'Database file path (default: {default_db_path})')

    # Couchbase connection arguments
    parser.add_argument('--couchbase-host', type=str, default=None,
                        help='Couchbase host (e.g., 192.168.1.100)')
    parser.add_argument('--couchbase-port', type=int, default=8091,
                        help='Couchbase port (default: 8091)')
    parser.add_argument('--couchbase-username', type=str, default='',
                        help='Couchbase username')
    parser.add_argument('--couchbase-password', type=str, default='',
                        help='Couchbase password')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Collect command
    collect_parser = subparsers.add_parser('collect', help='Collect a new snapshot')
    collect_parser.add_argument('--workers', type=int, default=20,
                                help='Number of parallel workers (default: 20)')
    collect_parser.set_defaults(func=collect_command)

    # Report command
    report_parser = subparsers.add_parser('report', help='Generate wrapped report')
    report_parser.add_argument('--start-date', type=str, default=None,
                               help='Start date (YYYY-MM-DD)')
    report_parser.add_argument('--end-date', type=str, default=None,
                               help='End date (YYYY-MM-DD)')
    report_parser.add_argument('--limit', type=int, default=10,
                               help='Number of top items to show (default: 10)')
    report_parser.set_defaults(func=report_command)

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show database statistics')
    stats_parser.set_defaults(func=stats_command)

    args = parser.parse_args()

    # Configure logging based on verbosity
    configure_logging(args.verbose)

    if args.command is None:
        parser.print_help()
        return

    # Initialize Couchbase config from CLI args and environment
    couchbase_config = CouchbaseConfig.from_args_and_env(args)

    # Initialize backend manager
    backend_manager = BackendManager(str(args.db_path), couchbase_config)

    # Connect to backend
    if not backend_manager.connect():
        logger.error("Failed to connect to any database backend")
        sys.exit(1)

    # Log which backend we're using
    if backend_manager.is_using_couchbase():
        logger.info(f"Using Couchbase backend at {couchbase_config.host}")
    else:
        logger.info(f"Using SQLite backend at {args.db_path}")

    try:
        # Execute command
        args.func(backend_manager, args)

        # If we just finished collecting and we're using SQLite, try to sync to Couchbase
        if args.command == 'collect' and backend_manager.is_using_sqlite() and couchbase_config.is_configured():
            logger.info("Attempting to reconnect to Couchbase for sync")
            if backend_manager.try_reconnect_couchbase():
                logger.info("Successfully reconnected to Couchbase, starting sync")
                sync_manager = SyncManager(
                    backend_manager.sqlite_backend,
                    backend_manager.couchbase_backend
                )
                if sync_manager.needs_sync():
                    logger.info("Syncing data from SQLite to Couchbase")
                    if sync_manager.sync():
                        logger.info("Sync completed successfully")
                    else:
                        logger.warning("Sync completed with errors, check logs")
                else:
                    logger.info("No data to sync")
            else:
                logger.debug("Couchbase still unavailable, sync deferred")

    finally:
        backend_manager.disconnect()


if __name__ == '__main__':
    main()