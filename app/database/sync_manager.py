#!/usr/bin/env python3
"""
Sync Manager for syncing data from SQLite to Couchbase

Handles multi-run offline scenarios where multiple snapshots accumulate
in SQLite while Couchbase is unavailable.
"""

import json
import os
from typing import Dict
from datetime import datetime

from app.database.sqlite_backend import SQLiteBackend
from app.database.couchbase_backend import CouchbaseBackend
from app.logging_config import logger


class SyncManager:
    """
    Manages syncing data from SQLite to Couchbase

    Features:
    - Tracks sync state in .sync_state.json file
    - Incremental sync (only new snapshots since last sync)
    - Preserves snapshot IDs during sync
    - Handles partial failures and resumption
    - Idempotent sync operations
    """

    def __init__(
        self,
        sqlite_backend: SQLiteBackend,
        couchbase_backend: CouchbaseBackend,
        state_file: str = ".sync_state.json",
    ):
        """
        Initialize sync manager

        Args:
            sqlite_backend: Source SQLite backend
            couchbase_backend: Target Couchbase backend
            state_file: Path to sync state file
        """
        self.sqlite = sqlite_backend
        self.couchbase = couchbase_backend
        self.state_file = state_file
        self.sync_state = self._load_sync_state()

    def _load_sync_state(self) -> Dict:
        """Load sync state from file"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                    logger.debug(
                        f"Loaded sync state: last_synced_snapshot_id={state.get('last_synced_snapshot_id')}"
                    )
                    return state
            except Exception as e:
                logger.warning(
                    f"Failed to load sync state file: {str(e)}, starting fresh"
                )
                return self._default_sync_state()
        else:
            logger.debug("No sync state file found, starting fresh sync")
            return self._default_sync_state()

    def _default_sync_state(self) -> Dict:
        """Return default sync state"""
        return {
            "last_synced_snapshot_id": 0,
            "last_sync_timestamp": None,
            "last_sync_status": None,
        }

    def _save_sync_state(self):
        """Save current sync state to file"""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.sync_state, f, indent=2)
            logger.debug(
                f"Saved sync state: last_synced_snapshot_id={self.sync_state['last_synced_snapshot_id']}"
            )
        except Exception as e:
            logger.error(f"Failed to save sync state: {str(e)}")

    def needs_sync(self) -> bool:
        """
        Check if there are new snapshots to sync

        Returns:
            bool: True if there are unsynced snapshots
        """
        last_synced = self.sync_state["last_synced_snapshot_id"]
        snapshots = self.sqlite.get_all_snapshots()

        # Check if there are any snapshots with ID > last_synced
        unsynced = [s for s in snapshots if s["snapshot_id"] > last_synced]

        if unsynced:
            logger.info(
                f"Found {len(unsynced)} unsynced snapshots (IDs: {[s['snapshot_id'] for s in unsynced]})"
            )
            return True
        else:
            logger.debug("No unsynced snapshots found")
            return False

    def sync(self) -> bool:
        """
        Sync all unsynced data from SQLite to Couchbase

        Returns:
            bool: True if sync completed successfully, False if any errors
        """
        logger.info("Starting sync from SQLite to Couchbase")

        # Get unsynced snapshots
        last_synced = self.sync_state["last_synced_snapshot_id"]
        all_snapshots = self.sqlite.get_all_snapshots()
        unsynced_snapshots = [
            s for s in all_snapshots if s["snapshot_id"] > last_synced
        ]

        if not unsynced_snapshots:
            logger.info("No snapshots to sync")
            return True

        logger.info(
            f"Syncing {len(unsynced_snapshots)} snapshots (IDs: {[s['snapshot_id'] for s in unsynced_snapshots]})"
        )

        # Sync each snapshot
        for snapshot in sorted(unsynced_snapshots, key=lambda x: x["snapshot_id"]):
            snapshot_id = snapshot["snapshot_id"]
            logger.info(f"Syncing snapshot {snapshot_id}")

            try:
                # Sync this snapshot and all its related data
                self._sync_snapshot(snapshot)

                # Update sync state after successful sync
                self.sync_state["last_synced_snapshot_id"] = snapshot_id
                self.sync_state["last_sync_timestamp"] = datetime.now().isoformat()
                self.sync_state["last_sync_status"] = "success"
                self._save_sync_state()

                logger.info(f"Successfully synced snapshot {snapshot_id}")

            except Exception as e:
                logger.error(f"Failed to sync snapshot {snapshot_id}: {str(e)}")
                self.sync_state["last_sync_status"] = (
                    f"failed_at_snapshot_{snapshot_id}"
                )
                self._save_sync_state()
                return False

        logger.info(
            f"Sync completed successfully, synced {len(unsynced_snapshots)} snapshots"
        )
        return True

    def _sync_snapshot(self, snapshot: Dict):
        """
        Sync a single snapshot and all its related data

        Order of operations (maintains referential integrity):
        1. Sync tracks referenced by this snapshot's play_history
        2. Sync the snapshot itself (with preserved snapshot_id)
        3. Sync play_history for this snapshot
        4. Sync daily_plays within the snapshot's date range

        Args:
            snapshot: Snapshot data dictionary
        """
        snapshot_id = snapshot["snapshot_id"]

        # Get all play_history for this snapshot
        play_history = self.sqlite.get_play_history_for_snapshot(snapshot_id)

        # 1. Sync all tracks referenced in play_history
        logger.debug(f"Syncing {len(play_history)} tracks for snapshot {snapshot_id}")
        track_ids = {ph["persistent_id"] for ph in play_history}
        for track_id in track_ids:
            track = self.sqlite.get_track(track_id)
            if track:
                self._sync_track(track)

        # 2. Sync the snapshot itself (preserving snapshot_id)
        logger.debug(f"Syncing snapshot {snapshot_id} metadata")
        self._sync_snapshot_metadata(snapshot)

        # 3. Sync play_history for this snapshot
        logger.debug(
            f"Syncing {len(play_history)} play history records for snapshot {snapshot_id}"
        )
        for history in play_history:
            self._sync_play_history(history)

        # 4. Sync daily_plays (find relevant date range from play_history)
        if play_history:
            dates = {
                ph.get("played_date") for ph in play_history if ph.get("played_date")
            }
            logger.debug(f"Syncing daily plays for {len(dates)} dates")
            for date in dates:
                for track_id in track_ids:
                    daily_play = self.sqlite.get_daily_play(track_id, date)
                    if daily_play:
                        self._sync_daily_play(daily_play)

    def _sync_track(self, track: Dict):
        """
        Sync a single track to Couchbase

        Uses upsert to handle duplicates - merges based on last_seen timestamp
        """
        try:
            # Check if track already exists in Couchbase
            existing = self.couchbase.get_track(track["persistent_id"])

            if existing:
                # Merge: keep track with most recent last_seen
                existing_last_seen = existing.get("last_seen", "")
                new_last_seen = track.get("last_seen", "")

                if new_last_seen > existing_last_seen:
                    # SQLite version is newer, upsert it
                    self.couchbase.upsert_track(track)
                    logger.debug(
                        f"Updated track {track['persistent_id']} (newer version from SQLite)"
                    )
                else:
                    logger.debug(
                        f"Skipped track {track['persistent_id']} (Couchbase version is newer)"
                    )
            else:
                # Track doesn't exist, insert it
                self.couchbase.upsert_track(track)
                logger.debug(f"Inserted track {track['persistent_id']}")

        except Exception as e:
            logger.error(f"Failed to sync track {track['persistent_id']}: {str(e)}")
            raise

    def _sync_snapshot_metadata(self, snapshot: Dict):
        """
        Sync snapshot metadata to Couchbase, preserving snapshot_id

        Note: We directly upsert the document instead of using create_snapshot()
        to preserve the snapshot_id from SQLite
        """
        try:
            snapshot_id = snapshot["snapshot_id"]

            # Check if snapshot already exists
            existing_snapshots = self.couchbase.get_all_snapshots()
            exists = any(s["snapshot_id"] == snapshot_id for s in existing_snapshots)

            if exists:
                logger.debug(
                    f"Snapshot {snapshot_id} already exists in Couchbase, skipping"
                )
                return

            # Upsert snapshot directly to preserve snapshot_id
            # We need to access the collection directly
            self.couchbase.collections["snapshots"].upsert(str(snapshot_id), snapshot)

            # Also update the counter to ensure future snapshots have higher IDs
            try:
                current_counter = self.couchbase.collections["counters"].get(
                    "snapshot_id"
                )
                current_value = current_counter.content_as[int]

                if snapshot_id > current_value:
                    # Set counter to at least this snapshot_id
                    self.couchbase.collections["counters"].upsert(
                        "snapshot_id", snapshot_id
                    )
                    logger.debug(f"Updated snapshot_id counter to {snapshot_id}")
            except Exception:
                # Counter doesn't exist yet, initialize it
                self.couchbase.collections["counters"].upsert(
                    "snapshot_id", snapshot_id
                )
                logger.debug(f"Initialized snapshot_id counter to {snapshot_id}")

            logger.debug(f"Synced snapshot {snapshot_id} metadata")

        except Exception as e:
            logger.error(
                f"Failed to sync snapshot metadata {snapshot['snapshot_id']}: {str(e)}"
            )
            raise

    def _sync_play_history(self, history: Dict):
        """Sync a single play_history record to Couchbase"""
        try:
            # Check if already exists (idempotent)
            snapshot_id = history["snapshot_id"]
            persistent_id = history["persistent_id"]

            existing_history = self.couchbase.get_play_history_for_snapshot(snapshot_id)
            exists = any(h["persistent_id"] == persistent_id for h in existing_history)

            if exists:
                logger.debug(
                    f"Play history for snapshot {snapshot_id}, track {persistent_id} already exists, skipping"
                )
                return

            self.couchbase.insert_play_history(history)
            logger.debug(
                f"Synced play history for snapshot {snapshot_id}, track {persistent_id}"
            )

        except Exception as e:
            logger.error(f"Failed to sync play history: {str(e)}")
            raise

    def _sync_daily_play(self, daily_play: Dict):
        """Sync a single daily_play record to Couchbase"""
        try:
            date = daily_play["date"]
            persistent_id = daily_play["persistent_id"]

            # Check if already exists
            existing = self.couchbase.get_daily_play(persistent_id, date)

            if existing:
                # Merge the deltas (accumulate)
                existing["plays_delta"] += daily_play.get("plays_delta", 0)
                existing["skips_delta"] += daily_play.get("skips_delta", 0)

                # Update with merged data
                self.couchbase.upsert_daily_play(existing)
                logger.debug(f"Merged daily play for {date}, track {persistent_id}")
            else:
                # Insert new
                self.couchbase.upsert_daily_play(daily_play)
                logger.debug(f"Synced daily play for {date}, track {persistent_id}")

        except Exception as e:
            logger.error(f"Failed to sync daily play: {str(e)}")
            raise

    def get_sync_status(self) -> Dict:
        """
        Get current sync status

        Returns:
            Dict with sync state information
        """
        return {
            "last_synced_snapshot_id": self.sync_state["last_synced_snapshot_id"],
            "last_sync_timestamp": self.sync_state["last_sync_timestamp"],
            "last_sync_status": self.sync_state["last_sync_status"],
            "needs_sync": self.needs_sync(),
        }
