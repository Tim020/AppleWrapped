#!/usr/bin/env python3
"""
Couchbase backend implementation with native N1QL JOINs and transactions
"""

from contextlib import contextmanager
from typing import Optional, Dict, List
from datetime import timedelta

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, QueryOptions
from couchbase.exceptions import (
    DocumentNotFoundException,
)
from couchbase.management.collections import CollectionSpec

from app.database.abstract_backend import DatabaseBackend
from app.config import CouchbaseConfig
from app.logging_config import logger


class CouchbaseBackend(DatabaseBackend):
    """Couchbase implementation of the database backend"""

    def __init__(self, config: CouchbaseConfig):
        """
        Initialize Couchbase backend

        Args:
            config: CouchbaseConfig with connection details
        """
        self.config = config
        self.cluster = None
        self.bucket = None
        self.scope = None
        self.collections = {}
        self._connected = False

    def connect(self) -> bool:
        """Connect to Couchbase cluster and initialize collections"""
        try:
            if not self.config.is_configured():
                logger.warning("Couchbase is not configured")
                return False

            # Connect to cluster
            auth = PasswordAuthenticator(self.config.username, self.config.password)

            self.cluster = Cluster(
                self.config.get_connection_string(), ClusterOptions(auth)
            )

            # Wait for cluster to be ready
            self.cluster.wait_until_ready(timedelta(seconds=10))

            # Get bucket
            self.bucket = self.cluster.bucket(self.config.bucket_name)

            # Get scope (using _default)
            self.scope = self.bucket.scope(self.config.scope_name)

            # Ensure collections exist
            self._ensure_collections()

            # Store collection references
            self.collections = {
                "tracks": self.scope.collection(self.config.tracks_collection),
                "snapshots": self.scope.collection(self.config.snapshots_collection),
                "playhistory": self.scope.collection(
                    self.config.playhistory_collection
                ),
                "dailyplays": self.scope.collection(self.config.dailyplays_collection),
                "counters": self.scope.collection(self.config.counters_collection),
            }

            # Create indexes
            self._create_indexes()

            self._connected = True
            logger.info(
                f"Connected to Couchbase backend at {self.config.host}, bucket: {self.config.bucket_name}, scope: {self.config.scope_name}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to connect to Couchbase at {self.config.host}: {str(e)}"
            )
            self._connected = False
            return False

    def _ensure_collections(self):
        """Ensure all required collections exist, create if they don't"""
        try:
            collection_manager = self.bucket.collections()

            # Get existing collections in the scope
            try:
                all_scopes = collection_manager.get_all_scopes()
                scope_spec = next(
                    (s for s in all_scopes if s.name == self.config.scope_name), None
                )
                existing_collections = (
                    {c.name for c in scope_spec.collections} if scope_spec else set()
                )
            except Exception:
                existing_collections = set()

            # Collections to create
            required_collections = [
                self.config.tracks_collection,
                self.config.snapshots_collection,
                self.config.playhistory_collection,
                self.config.dailyplays_collection,
                self.config.counters_collection,
            ]

            # Create missing collections
            for coll_name in required_collections:
                if coll_name not in existing_collections:
                    collection_spec = CollectionSpec(
                        coll_name, scope_name=self.config.scope_name
                    )
                    collection_manager.create_collection(collection_spec)
                    logger.info(
                        f"Created Couchbase collection '{coll_name}' in scope '{self.config.scope_name}'"
                    )

        except Exception as e:
            logger.warning(f"Failed to create Couchbase collections: {str(e)}")
            # Don't fail connection if we can't create collections
            # They might already exist or we might not have permissions

    def _create_indexes(self):
        """Create N1QL indexes for query performance"""
        try:
            # Index creation queries
            indexes = [
                # DailyPlays indexes (for date range queries)
                f"""CREATE INDEX IF NOT EXISTS idx_dailyplays_date
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}`(date)""",
                f"""CREATE INDEX IF NOT EXISTS idx_dailyplays_persistent_id
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}`(persistent_id)""",
                # Tracks indexes
                f"""CREATE INDEX IF NOT EXISTS idx_tracks_artist
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}`(artist)""",
                f"""CREATE INDEX IF NOT EXISTS idx_tracks_genre
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}`(genre)""",
                # PlayHistory indexes
                f"""CREATE INDEX IF NOT EXISTS idx_playhistory_snapshot
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.playhistory_collection}`(snapshot_id)""",
                # Snapshots indexes
                f"""CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
                    ON `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.snapshots_collection}`(timestamp)""",
            ]

            for index_query in indexes:
                try:
                    self.cluster.query(index_query).execute()
                except Exception as e:
                    logger.debug(
                        f"Skipped index creation (may already exist): {index_query[:50]}... - {str(e)}"
                    )

            logger.info("Successfully created Couchbase indexes")

        except Exception as e:
            logger.warning(f"Failed to create Couchbase indexes: {str(e)}")

    def is_healthy(self) -> bool:
        """Check if Couchbase backend is healthy"""
        if not self._connected or not self.cluster:
            return False

        try:
            # Quick health check query
            self.cluster.query(
                f"SELECT RAW COUNT(*) FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` LIMIT 1"
            ).execute()
            return True
        except Exception as e:
            logger.debug(f"Couchbase health check failed: {str(e)}")
            return False

    def disconnect(self):
        """Disconnect from Couchbase"""
        if self.cluster:
            self.cluster.close()
        self._connected = False
        logger.debug("Disconnected from Couchbase backend")

    @contextmanager
    def transaction(self):
        """
        Context manager for Couchbase transactions

        Note: This is a simplified transaction implementation.
        For full ACID transactions, use cluster.transactions.run()
        """
        # For now, we'll use a simple context manager
        # Full transaction support can be added later with cluster.transactions
        yield None

    # Track Operations

    def get_track(self, persistent_id: str) -> Optional[Dict]:
        """Get a track by persistent_id"""
        try:
            result = self.collections["tracks"].get(persistent_id)
            return result.content_as[dict]
        except DocumentNotFoundException:
            return None
        except Exception as e:
            logger.error(
                f"Failed to get track '{persistent_id}' from Couchbase: {str(e)}"
            )
            return None

    def upsert_track(self, track_data: Dict):
        """Insert or update a track"""
        try:
            persistent_id = track_data["persistent_id"]
            self.collections["tracks"].upsert(persistent_id, track_data)
        except Exception as e:
            logger.error(
                f"Failed to upsert track '{track_data.get('persistent_id')}' to Couchbase: {str(e)}"
            )
            raise

    def get_all_tracks(self) -> List[Dict]:
        """Get all tracks"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}`
            """
            result = self.cluster.query(query).execute()
            return [row[self.config.tracks_collection] for row in result]
        except Exception as e:
            logger.error(f"Failed to get all tracks from Couchbase: {str(e)}")
            return []

    # Snapshot Operations

    def create_snapshot(self, snapshot_data: Dict) -> int:
        """
        Create a new snapshot with auto-increment ID

        Uses atomic counter for snapshot_id generation
        """
        try:
            from couchbase.options import IncrementOptions, SignedInt64, DeltaValue

            # Increment counter atomically
            # If counter doesn't exist, it will be created starting at 1
            counter_result = (
                self.collections["counters"]
                .binary()
                .increment(
                    "snapshot_id",
                    IncrementOptions(initial=SignedInt64(1), delta=DeltaValue(1)),
                )
            )
            snapshot_id = counter_result.content

            # Add snapshot_id to data
            snapshot_doc = snapshot_data.copy()
            snapshot_doc["snapshot_id"] = snapshot_id

            # Store snapshot
            self.collections["snapshots"].upsert(str(snapshot_id), snapshot_doc)

            return snapshot_id

        except Exception as e:
            logger.error(f"Failed to create snapshot in Couchbase: {str(e)}")
            raise

    def get_previous_snapshot(self, before_timestamp: str) -> Optional[Dict]:
        """Get the most recent snapshot before a given timestamp"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.snapshots_collection}`
                WHERE timestamp < $before_timestamp
                ORDER BY timestamp DESC
                LIMIT 1
            """
            result = self.cluster.query(
                query,
                QueryOptions(named_parameters={"before_timestamp": before_timestamp}),
            ).execute()

            rows = list(result)
            if rows:
                return rows[0][self.config.snapshots_collection]
            return None

        except Exception as e:
            logger.error(f"Failed to get previous snapshot from Couchbase: {str(e)}")
            return None

    def get_all_snapshots(self) -> List[Dict]:
        """Get all snapshots"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.snapshots_collection}`
                ORDER BY snapshot_id
            """
            result = self.cluster.query(query).execute()
            return [row[self.config.snapshots_collection] for row in result]
        except Exception as e:
            logger.error(f"Failed to get all snapshots from Couchbase: {str(e)}")
            return []

    # PlayHistory Operations

    def get_play_history_for_snapshot(self, snapshot_id: int) -> List[Dict]:
        """Get all play history records for a snapshot"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.playhistory_collection}`
                WHERE snapshot_id = $snapshot_id
            """
            result = self.cluster.query(
                query, QueryOptions(named_parameters={"snapshot_id": snapshot_id})
            ).execute()

            return [row[self.config.playhistory_collection] for row in result]

        except Exception as e:
            logger.error(
                f"Failed to get play history for snapshot {snapshot_id} from Couchbase: {str(e)}"
            )
            return []

    def insert_play_history(self, history_data: Dict):
        """Insert a play history record"""
        try:
            # Use composite key: snapshot_id::persistent_id
            doc_id = f"{history_data['snapshot_id']}::{history_data['persistent_id']}"
            self.collections["playhistory"].upsert(doc_id, history_data)
        except Exception as e:
            logger.error(
                f"Failed to insert play history (snapshot: {history_data.get('snapshot_id')}, track: {history_data.get('persistent_id')}) to Couchbase: {str(e)}"
            )
            raise

    def get_all_play_history(self) -> List[Dict]:
        """Get all play history records"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.playhistory_collection}`
            """
            result = self.cluster.query(query).execute()
            return [row[self.config.playhistory_collection] for row in result]
        except Exception as e:
            logger.error(f"Failed to get all play history from Couchbase: {str(e)}")
            return []

    # DailyPlay Operations

    def upsert_daily_play(self, daily_data: Dict):
        """Insert or update a daily play record"""
        try:
            # Use composite key: date::persistent_id
            doc_id = f"{daily_data['date']}::{daily_data['persistent_id']}"

            # Try to get existing document
            try:
                existing = self.collections["dailyplays"].get(doc_id)
                existing_data = existing.content_as[dict]

                # Accumulate deltas
                existing_data["plays_delta"] += daily_data.get("plays_delta", 0)
                existing_data["skips_delta"] += daily_data.get("skips_delta", 0)

                self.collections["dailyplays"].upsert(doc_id, existing_data)
            except DocumentNotFoundException:
                # Document doesn't exist, create new
                self.collections["dailyplays"].upsert(doc_id, daily_data)

        except Exception as e:
            logger.error(
                f"Failed to upsert daily play (date: {daily_data.get('date')}, track: {daily_data.get('persistent_id')}) to Couchbase: {str(e)}"
            )
            raise

    def get_daily_play(self, persistent_id: str, date: str) -> Optional[Dict]:
        """Get a daily play record"""
        try:
            doc_id = f"{date}::{persistent_id}"
            result = self.collections["dailyplays"].get(doc_id)
            return result.content_as[dict]
        except DocumentNotFoundException:
            return None
        except Exception as e:
            logger.error(
                f"Failed to get daily play for track '{persistent_id}' on date '{date}' from Couchbase: {str(e)}"
            )
            return None

    def get_all_daily_plays(self) -> List[Dict]:
        """Get all daily play records"""
        try:
            query = f"""
                SELECT *
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}`
            """
            result = self.cluster.query(query).execute()
            return [row[self.config.dailyplays_collection] for row in result]
        except Exception as e:
            logger.error(f"Failed to get all daily plays from Couchbase: {str(e)}")
            return []

    # Query Operations (Reporting) - Using Native N1QL JOINs

    def query_top_tracks(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top tracks by play count using N1QL JOIN"""
        try:
            query = f"""
                SELECT t.name, t.artist, SUM(dp.plays_delta) as plays
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
                GROUP BY t.name, t.artist, t.persistent_id
                ORDER BY SUM(dp.plays_delta) DESC
                LIMIT $limit
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    }
                ),
            ).execute()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to query top tracks from Couchbase: {str(e)}")
            return []

    def query_top_artists(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top artists by play count using N1QL JOIN"""
        try:
            query = f"""
                SELECT t.artist, SUM(dp.plays_delta) as plays
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
                  AND t.artist IS NOT NULL
                GROUP BY t.artist
                ORDER BY SUM(dp.plays_delta) DESC
                LIMIT $limit
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    }
                ),
            ).execute()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to query top artists from Couchbase: {str(e)}")
            return []

    def query_top_albums(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top albums by play count using N1QL JOIN"""
        try:
            query = f"""
                SELECT t.album, t.artist, SUM(dp.plays_delta) as plays
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
                  AND t.album IS NOT NULL
                GROUP BY t.album, t.artist
                ORDER BY SUM(dp.plays_delta) DESC
                LIMIT $limit
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    }
                ),
            ).execute()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to query top albums from Couchbase: {str(e)}")
            return []

    def query_top_genres(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top genres by play count using N1QL JOIN"""
        try:
            query = f"""
                SELECT t.genre, SUM(dp.plays_delta) as plays
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
                  AND t.genre IS NOT NULL
                GROUP BY t.genre
                ORDER BY SUM(dp.plays_delta) DESC
                LIMIT $limit
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    }
                ),
            ).execute()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to query top genres from Couchbase: {str(e)}")
            return []

    def query_most_skipped(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query most skipped tracks using N1QL JOIN"""
        try:
            query = f"""
                SELECT t.name, t.artist, SUM(dp.skips_delta) as skips
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
                  AND dp.skips_delta > 0
                GROUP BY t.name, t.artist, t.persistent_id
                ORDER BY SUM(dp.skips_delta) DESC
                LIMIT $limit
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    }
                ),
            ).execute()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(
                f"Failed to query most skipped tracks from Couchbase: {str(e)}"
            )
            return []

    def query_listening_stats(self, start_date: str, end_date: str) -> Dict:
        """Query listening statistics using N1QL JOIN"""
        try:
            query = f"""
                SELECT
                    SUM(dp.plays_delta) as total_plays,
                    SUM(dp.skips_delta) as total_skips,
                    COUNT(DISTINCT dp.persistent_id) as unique_tracks,
                    SUM(dp.plays_delta * t.duration) as total_time
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}` dp
                JOIN `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}` t
                    ON KEYS dp.persistent_id
                WHERE dp.date >= $start_date
                  AND dp.date <= $end_date
            """

            result = self.cluster.query(
                query,
                QueryOptions(
                    named_parameters={"start_date": start_date, "end_date": end_date}
                ),
            ).execute()

            rows = list(result)
            if rows:
                stats = dict(rows[0])
                return {
                    "total_plays": stats.get("total_plays") or 0,
                    "total_skips": stats.get("total_skips") or 0,
                    "unique_tracks": stats.get("unique_tracks") or 0,
                    "total_time": stats.get("total_time") or 0,
                }

            return {
                "total_plays": 0,
                "total_skips": 0,
                "unique_tracks": 0,
                "total_time": 0,
            }

        except Exception as e:
            logger.error(f"Failed to query listening stats from Couchbase: {str(e)}")
            return {
                "total_plays": 0,
                "total_skips": 0,
                "unique_tracks": 0,
                "total_time": 0,
            }

    def query_stats(self) -> Dict:
        """Query overall database statistics"""
        try:
            # Get track count
            track_query = f"""
                SELECT RAW COUNT(*)
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.tracks_collection}`
            """
            track_result = self.cluster.query(track_query).execute()
            total_tracks = list(track_result)[0] if track_result else 0

            # Get snapshot count
            snapshot_query = f"""
                SELECT RAW COUNT(*)
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.snapshots_collection}`
            """
            snapshot_result = self.cluster.query(snapshot_query).execute()
            total_snapshots = list(snapshot_result)[0] if snapshot_result else 0

            # Get earliest and latest dates
            date_query = f"""
                SELECT MIN(date) as earliest_date, MAX(date) as latest_date
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.dailyplays_collection}`
            """
            date_result = self.cluster.query(date_query).execute()
            date_rows = list(date_result)

            earliest_date = None
            latest_date = None
            if date_rows:
                earliest_date = date_rows[0].get("earliest_date")
                latest_date = date_rows[0].get("latest_date")

            # Get earliest and latest snapshots
            snapshot_time_query = f"""
                SELECT MIN(timestamp) as earliest_snapshot, MAX(timestamp) as latest_snapshot
                FROM `{self.config.bucket_name}`.`{self.config.scope_name}`.`{self.config.snapshots_collection}`
            """
            snapshot_time_result = self.cluster.query(snapshot_time_query).execute()
            snapshot_time_rows = list(snapshot_time_result)

            earliest_snapshot = None
            latest_snapshot = None
            if snapshot_time_rows:
                earliest_snapshot = snapshot_time_rows[0].get("earliest_snapshot")
                latest_snapshot = snapshot_time_rows[0].get("latest_snapshot")

            return {
                "total_tracks": total_tracks,
                "total_snapshots": total_snapshots,
                "earliest_date": earliest_date,
                "latest_date": latest_date,
                "earliest_snapshot": earliest_snapshot,
                "latest_snapshot": latest_snapshot,
            }

        except Exception as e:
            logger.error(f"Failed to query overall stats from Couchbase: {str(e)}")
            return {
                "total_tracks": 0,
                "total_snapshots": 0,
                "earliest_date": None,
                "latest_date": None,
                "earliest_snapshot": None,
                "latest_snapshot": None,
            }
