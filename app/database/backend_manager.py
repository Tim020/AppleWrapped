#!/usr/bin/env python3
"""
Backend manager for automatic failover between Couchbase and SQLite
"""

import os
from typing import Optional, Dict, List
from contextlib import contextmanager

from app.database.abstract_backend import DatabaseBackend
from app.database.sqlite_backend import SQLiteBackend
from app.database.couchbase_backend import CouchbaseBackend
from app.config import CouchbaseConfig
from app.logging_config import logger


class BackendManager(DatabaseBackend):
    """
    Manages database backends with automatic failover

    - Primary: Couchbase (if configured)
    - Fallback: SQLite (always available)
    - Automatic health checking and failover
    - Sync trigger when switching back to Couchbase
    """

    def __init__(self, db_path: str, couchbase_config: CouchbaseConfig):
        """
        Initialize backend manager

        Args:
            db_path: Path to SQLite database file (fallback)
            couchbase_config: Couchbase configuration
        """
        self.db_path = db_path
        self.couchbase_config = couchbase_config

        self.couchbase_backend: Optional[CouchbaseBackend] = None
        self.sqlite_backend: Optional[SQLiteBackend] = None
        self.active_backend: Optional[DatabaseBackend] = None

        self._force_sqlite = os.environ.get("FORCE_SQLITE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to backends with automatic failover logic

        Tries Couchbase first, falls back to SQLite if:
        - Couchbase not configured
        - Couchbase connection fails
        - FORCE_SQLITE environment variable is set
        """
        # Check if we should force SQLite
        if self._force_sqlite:
            logger.info(
                "Forcing SQLite backend due to FORCE_SQLITE environment variable"
            )
            return self._connect_sqlite()

        # Try Couchbase first if configured
        if self.couchbase_config.is_configured():
            logger.info(
                f"Attempting to connect to Couchbase at {self.couchbase_config.host}"
            )

            self.couchbase_backend = CouchbaseBackend(self.couchbase_config)

            if self.couchbase_backend.connect():
                self.active_backend = self.couchbase_backend
                self._connected = True
                logger.info(
                    f"Successfully connected to Couchbase at {self.couchbase_config.host}"
                )
                return True
            else:
                logger.warning("Couchbase connection failed, falling back to SQLite")
                return self._connect_sqlite()
        else:
            logger.info("Couchbase not configured, using SQLite backend")
            return self._connect_sqlite()

    def _connect_sqlite(self) -> bool:
        """Connect to SQLite backend"""
        self.sqlite_backend = SQLiteBackend(self.db_path)

        if self.sqlite_backend.connect():
            self.active_backend = self.sqlite_backend
            self._connected = True
            logger.info(f"Using SQLite backend at {self.db_path}")
            return True
        else:
            logger.error(f"SQLite connection failed for database at {self.db_path}")
            return False

    def is_healthy(self) -> bool:
        """Check if the active backend is healthy"""
        if not self._connected or not self.active_backend:
            return False

        return self.active_backend.is_healthy()

    def is_using_couchbase(self) -> bool:
        """Check if currently using Couchbase backend"""
        return (
            self.active_backend is self.couchbase_backend
            and self.couchbase_backend is not None
        )

    def is_using_sqlite(self) -> bool:
        """Check if currently using SQLite backend"""
        return (
            self.active_backend is self.sqlite_backend
            and self.sqlite_backend is not None
        )

    def try_reconnect_couchbase(self) -> bool:
        """
        Attempt to reconnect to Couchbase (used for periodic health checks)

        Returns:
            bool: True if switched to Couchbase, False if staying on SQLite
        """
        # Only try if we're currently using SQLite and Couchbase is configured
        if not self.is_using_sqlite():
            return False

        if not self.couchbase_config.is_configured() or self._force_sqlite:
            return False

        logger.info("Attempting to reconnect to Couchbase")

        # Try to connect to Couchbase
        if self.couchbase_backend is None:
            self.couchbase_backend = CouchbaseBackend(self.couchbase_config)

        if self.couchbase_backend.connect():
            logger.info("Successfully reconnected to Couchbase, switching from SQLite")
            self.active_backend = self.couchbase_backend
            return True
        else:
            logger.debug("Couchbase still unavailable")
            return False

    def disconnect(self):
        """Disconnect from all backends"""
        if self.couchbase_backend:
            self.couchbase_backend.disconnect()

        if self.sqlite_backend:
            self.sqlite_backend.disconnect()

        self.active_backend = None
        self._connected = False
        logger.info("Disconnected from all backends")

    @contextmanager
    def transaction(self):
        """Context manager for transactions (delegates to active backend)"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")

        with self.active_backend.transaction() as txn:
            yield txn

    # Delegate all operations to active backend

    def get_track(self, persistent_id: str) -> Optional[Dict]:
        """Get a track by persistent_id"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_track(persistent_id)

    def upsert_track(self, track_data: Dict):
        """Insert or update a track"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")

        try:
            self.active_backend.upsert_track(track_data)
        except Exception as e:
            # If operation fails and we're using Couchbase, try failover
            if self.is_using_couchbase():
                logger.error(
                    f"Operation 'upsert_track' failed on Couchbase: {str(e)}, failing over to SQLite"
                )
                if self._failover_to_sqlite():
                    # Retry on SQLite
                    self.active_backend.upsert_track(track_data)
                else:
                    raise
            else:
                raise

    def get_all_tracks(self) -> List[Dict]:
        """Get all tracks"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_all_tracks()

    def create_snapshot(self, snapshot_data: Dict) -> int:
        """Create a new snapshot"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")

        try:
            return self.active_backend.create_snapshot(snapshot_data)
        except Exception as e:
            if self.is_using_couchbase():
                logger.error(
                    f"Operation 'create_snapshot' failed on Couchbase: {str(e)}, failing over to SQLite"
                )
                if self._failover_to_sqlite():
                    return self.active_backend.create_snapshot(snapshot_data)
                else:
                    raise
            else:
                raise

    def get_previous_snapshot(self, before_timestamp: str) -> Optional[Dict]:
        """Get the most recent snapshot before a given timestamp"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_previous_snapshot(before_timestamp)

    def get_all_snapshots(self) -> List[Dict]:
        """Get all snapshots"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_all_snapshots()

    def get_play_history_for_snapshot(self, snapshot_id: int) -> List[Dict]:
        """Get all play history records for a snapshot"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_play_history_for_snapshot(snapshot_id)

    def insert_play_history(self, history_data: Dict):
        """Insert a play history record"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")

        try:
            self.active_backend.insert_play_history(history_data)
        except Exception as e:
            if self.is_using_couchbase():
                logger.error(
                    f"Operation 'insert_play_history' failed on Couchbase: {str(e)}, failing over to SQLite"
                )
                if self._failover_to_sqlite():
                    self.active_backend.insert_play_history(history_data)
                else:
                    raise
            else:
                raise

    def get_all_play_history(self) -> List[Dict]:
        """Get all play history records"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_all_play_history()

    def upsert_daily_play(self, daily_data: Dict):
        """Insert or update a daily play record"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")

        try:
            self.active_backend.upsert_daily_play(daily_data)
        except Exception as e:
            if self.is_using_couchbase():
                logger.error(
                    f"Operation 'upsert_daily_play' failed on Couchbase: {str(e)}, failing over to SQLite"
                )
                if self._failover_to_sqlite():
                    self.active_backend.upsert_daily_play(daily_data)
                else:
                    raise
            else:
                raise

    def get_daily_play(self, persistent_id: str, date: str) -> Optional[Dict]:
        """Get a daily play record"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_daily_play(persistent_id, date)

    def get_all_daily_plays(self) -> List[Dict]:
        """Get all daily play records"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.get_all_daily_plays()

    def query_top_tracks(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top tracks by play count"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_top_tracks(start_date, end_date, limit)

    def query_top_artists(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top artists by play count"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_top_artists(start_date, end_date, limit)

    def query_top_albums(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top albums by play count"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_top_albums(start_date, end_date, limit)

    def query_top_genres(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top genres by play count"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_top_genres(start_date, end_date, limit)

    def query_most_skipped(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query most skipped tracks"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_most_skipped(start_date, end_date, limit)

    def query_listening_stats(self, start_date: str, end_date: str) -> Dict:
        """Query listening statistics"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_listening_stats(start_date, end_date)

    def query_stats(self) -> Dict:
        """Query overall database statistics"""
        if not self.active_backend:
            raise RuntimeError("No active backend available")
        return self.active_backend.query_stats()

    def _failover_to_sqlite(self) -> bool:
        """
        Internal method to failover from Couchbase to SQLite

        Returns:
            bool: True if failover successful, False otherwise
        """
        logger.warning("Failing over from Couchbase to SQLite")

        # Ensure SQLite backend is available
        if not self.sqlite_backend:
            if not self._connect_sqlite():
                logger.error("Failover failed: SQLite backend unavailable")
                return False

        # Switch to SQLite
        self.active_backend = self.sqlite_backend
        logger.info("Successfully failed over to SQLite backend")
        return True
