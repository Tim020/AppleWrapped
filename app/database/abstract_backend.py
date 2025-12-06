#!/usr/bin/env python3
"""
Abstract base class defining the database backend interface
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from contextlib import contextmanager


class DatabaseBackend(ABC):
    """Abstract interface for database backends (SQLite, Couchbase, etc.)"""

    # Connection Management

    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to the database backend

        Returns:
            bool: True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """
        Check if the backend is healthy and responsive

        Returns:
            bool: True if healthy, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from the database backend"""
        pass

    @abstractmethod
    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions

        Usage:
            with backend.transaction():
                # perform operations
                # auto-commit on success, rollback on exception
        """
        pass

    # Track Operations

    @abstractmethod
    def get_track(self, persistent_id: str) -> Optional[Dict]:
        """
        Get a track by persistent_id

        Args:
            persistent_id: The track's persistent ID

        Returns:
            Dict with track data or None if not found
        """
        pass

    @abstractmethod
    def upsert_track(self, track_data: Dict):
        """
        Insert or update a track

        Args:
            track_data: Dictionary containing track fields
        """
        pass

    @abstractmethod
    def get_all_tracks(self) -> List[Dict]:
        """
        Get all tracks (for sync purposes)

        Returns:
            List of track dictionaries
        """
        pass

    # Snapshot Operations

    @abstractmethod
    def create_snapshot(self, snapshot_data: Dict) -> int:
        """
        Create a new snapshot

        Args:
            snapshot_data: Dictionary with snapshot fields (timestamp, total_tracks, etc.)

        Returns:
            int: The snapshot_id of the created snapshot
        """
        pass

    @abstractmethod
    def get_previous_snapshot(self, before_timestamp: str) -> Optional[Dict]:
        """
        Get the most recent snapshot before a given timestamp

        Args:
            before_timestamp: ISO format timestamp

        Returns:
            Dict with snapshot data or None if not found
        """
        pass

    @abstractmethod
    def get_all_snapshots(self) -> List[Dict]:
        """
        Get all snapshots (for sync purposes)

        Returns:
            List of snapshot dictionaries
        """
        pass

    # PlayHistory Operations

    @abstractmethod
    def get_play_history_for_snapshot(self, snapshot_id: int) -> List[Dict]:
        """
        Get all play history records for a snapshot

        Args:
            snapshot_id: The snapshot ID

        Returns:
            List of play history dictionaries
        """
        pass

    @abstractmethod
    def insert_play_history(self, history_data: Dict):
        """
        Insert a play history record

        Args:
            history_data: Dictionary with play history fields
        """
        pass

    @abstractmethod
    def get_all_play_history(self) -> List[Dict]:
        """
        Get all play history records (for sync purposes)

        Returns:
            List of play history dictionaries
        """
        pass

    # DailyPlay Operations

    @abstractmethod
    def upsert_daily_play(self, daily_data: Dict):
        """
        Insert or update a daily play record

        Args:
            daily_data: Dictionary with daily play fields
        """
        pass

    @abstractmethod
    def get_daily_play(self, persistent_id: str, date: str) -> Optional[Dict]:
        """
        Get a daily play record

        Args:
            persistent_id: The track's persistent ID
            date: Date in YYYY-MM-DD format

        Returns:
            Dict with daily play data or None if not found
        """
        pass

    @abstractmethod
    def get_all_daily_plays(self) -> List[Dict]:
        """
        Get all daily play records (for sync purposes)

        Returns:
            List of daily play dictionaries
        """
        pass

    # Query Operations (Reporting)

    @abstractmethod
    def query_top_tracks(self, start_date: str, end_date: str, limit: int) -> List[Dict]:
        """
        Query top tracks by play count in date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of results to return

        Returns:
            List of dicts with keys: name, artist, plays
        """
        pass

    @abstractmethod
    def query_top_artists(self, start_date: str, end_date: str, limit: int) -> List[Dict]:
        """
        Query top artists by play count in date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of results to return

        Returns:
            List of dicts with keys: artist, plays
        """
        pass

    @abstractmethod
    def query_top_albums(self, start_date: str, end_date: str, limit: int) -> List[Dict]:
        """
        Query top albums by play count in date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of results to return

        Returns:
            List of dicts with keys: album, artist, plays
        """
        pass

    @abstractmethod
    def query_top_genres(self, start_date: str, end_date: str, limit: int) -> List[Dict]:
        """
        Query top genres by play count in date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of results to return

        Returns:
            List of dicts with keys: genre, plays
        """
        pass

    @abstractmethod
    def query_most_skipped(self, start_date: str, end_date: str, limit: int) -> List[Dict]:
        """
        Query most skipped tracks in date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of results to return

        Returns:
            List of dicts with keys: name, artist, skips
        """
        pass

    @abstractmethod
    def query_listening_stats(self, start_date: str, end_date: str) -> Dict:
        """
        Query listening statistics for date range

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict with keys: total_plays, total_skips, unique_tracks, total_time
        """
        pass

    @abstractmethod
    def query_stats(self) -> Dict:
        """
        Query overall database statistics

        Returns:
            Dict with keys: total_tracks, total_snapshots, earliest_date, latest_date
        """
        pass
