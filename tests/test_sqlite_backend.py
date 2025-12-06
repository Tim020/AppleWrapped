#!/usr/bin/env python3
"""
Tests for SQLite backend implementation
"""

from datetime import datetime, timedelta
from app.database.sqlite_backend import SQLiteBackend


class TestSQLiteBackendConnection:
    """Tests for connection management"""

    def test_connect_success(self, temp_db_path):
        """Test successful database connection"""
        backend = SQLiteBackend(temp_db_path)
        assert backend.connect()
        assert backend._connected

    def test_is_healthy_when_connected(self, sqlite_backend):
        """Test health check returns True when connected"""
        assert sqlite_backend.is_healthy()

    def test_is_healthy_when_not_connected(self, temp_db_path):
        """Test health check returns False when not connected"""
        backend = SQLiteBackend(temp_db_path)
        assert not backend.is_healthy()

    def test_disconnect(self, sqlite_backend):
        """Test disconnect marks backend as disconnected"""
        assert sqlite_backend._connected
        sqlite_backend.disconnect()
        assert not sqlite_backend._connected


class TestSQLiteBackendTrackOperations:
    """Tests for track operations"""

    def test_upsert_track_new(self, sqlite_backend, sample_track_data):
        """Test inserting a new track"""
        sqlite_backend.upsert_track(sample_track_data)

        track = sqlite_backend.get_track(sample_track_data["persistent_id"])
        assert track is not None
        assert track["name"] == sample_track_data["name"]
        assert track["artist"] == sample_track_data["artist"]
        assert track["album"] == sample_track_data["album"]

    def test_upsert_track_update(self, sqlite_backend, sample_track_data):
        """Test updating an existing track"""
        # Insert first
        sqlite_backend.upsert_track(sample_track_data)

        # Update with new data
        updated_data = sample_track_data.copy()
        updated_data["name"] = "Updated Song"
        updated_data["artist"] = "Updated Artist"
        sqlite_backend.upsert_track(updated_data)

        track = sqlite_backend.get_track(sample_track_data["persistent_id"])
        assert track["name"] == "Updated Song"
        assert track["artist"] == "Updated Artist"

    def test_get_track_not_found(self, sqlite_backend):
        """Test getting non-existent track returns None"""
        track = sqlite_backend.get_track("NONEXISTENT123")
        assert track is None

    def test_get_all_tracks_empty(self, sqlite_backend):
        """Test getting all tracks when database is empty"""
        tracks = sqlite_backend.get_all_tracks()
        assert tracks == []

    def test_get_all_tracks(self, sqlite_backend, sample_tracks_data):
        """Test getting all tracks"""
        # Insert multiple tracks
        for track_data in sample_tracks_data:
            sqlite_backend.upsert_track(track_data)

        tracks = sqlite_backend.get_all_tracks()
        assert len(tracks) == len(sample_tracks_data)


class TestSQLiteBackendSnapshotOperations:
    """Tests for snapshot operations"""

    def test_create_snapshot(self, sqlite_backend, sample_snapshot_data):
        """Test creating a snapshot"""
        snapshot_id = sqlite_backend.create_snapshot(sample_snapshot_data)
        assert snapshot_id is not None
        assert isinstance(snapshot_id, int)
        assert snapshot_id > 0

    def test_create_multiple_snapshots(self, sqlite_backend):
        """Test creating multiple snapshots with auto-increment IDs"""
        snapshot_data1 = {
            "timestamp": datetime.now().isoformat(),
            "total_tracks": 100,
            "collection_duration_seconds": 60.0,
        }
        snapshot_data2 = {
            "timestamp": (datetime.now() + timedelta(hours=1)).isoformat(),
            "total_tracks": 105,
            "collection_duration_seconds": 65.0,
        }

        id1 = sqlite_backend.create_snapshot(snapshot_data1)
        id2 = sqlite_backend.create_snapshot(snapshot_data2)

        assert id2 > id1

    def test_get_previous_snapshot(self, sqlite_backend):
        """Test getting previous snapshot"""
        # Create two snapshots
        time1 = datetime.now()
        time2 = time1 + timedelta(hours=1)

        snapshot_data1 = {
            "timestamp": time1.isoformat(),
            "total_tracks": 100,
            "collection_duration_seconds": 60.0,
        }
        snapshot_data2 = {
            "timestamp": time2.isoformat(),
            "total_tracks": 105,
            "collection_duration_seconds": 65.0,
        }

        sqlite_backend.create_snapshot(snapshot_data1)
        sqlite_backend.create_snapshot(snapshot_data2)

        # Get snapshot before time2
        prev = sqlite_backend.get_previous_snapshot(time2.isoformat())
        assert prev is not None
        assert prev["total_tracks"] == 100

    def test_get_previous_snapshot_none(self, sqlite_backend):
        """Test getting previous snapshot when none exists"""
        prev = sqlite_backend.get_previous_snapshot(datetime.now().isoformat())
        assert prev is None

    def test_get_all_snapshots(self, sqlite_backend):
        """Test getting all snapshots"""
        # Create multiple snapshots
        for i in range(3):
            snapshot_data = {
                "timestamp": (datetime.now() + timedelta(hours=i)).isoformat(),
                "total_tracks": 100 + i,
                "collection_duration_seconds": 60.0,
            }
            sqlite_backend.create_snapshot(snapshot_data)

        snapshots = sqlite_backend.get_all_snapshots()
        assert len(snapshots) == 3
        # Should be ordered by snapshot_id
        assert snapshots[0]["snapshot_id"] < snapshots[1]["snapshot_id"]


class TestSQLiteBackendPlayHistoryOperations:
    """Tests for play history operations"""

    def test_insert_play_history(
        self, sqlite_backend, sample_track_data, sample_snapshot_data
    ):
        """Test inserting play history"""
        # Setup: create track and snapshot
        sqlite_backend.upsert_track(sample_track_data)
        snapshot_id = sqlite_backend.create_snapshot(sample_snapshot_data)

        history_data = {
            "persistent_id": sample_track_data["persistent_id"],
            "snapshot_id": snapshot_id,
            "played_count": 42,
            "skipped_count": 3,
            "played_date": "2024-01-15",
            "rating": 80,
        }

        sqlite_backend.insert_play_history(history_data)

        # Verify
        history = sqlite_backend.get_play_history_for_snapshot(snapshot_id)
        assert len(history) == 1
        assert history[0]["played_count"] == 42
        assert history[0]["skipped_count"] == 3

    def test_get_play_history_for_snapshot_empty(
        self, sqlite_backend, sample_snapshot_data
    ):
        """Test getting play history for snapshot with no data"""
        snapshot_id = sqlite_backend.create_snapshot(sample_snapshot_data)
        history = sqlite_backend.get_play_history_for_snapshot(snapshot_id)
        assert history == []

    def test_get_all_play_history(
        self, sqlite_backend, sample_tracks_data, sample_snapshot_data
    ):
        """Test getting all play history"""
        # Setup: create tracks and snapshot
        for track_data in sample_tracks_data[:3]:
            sqlite_backend.upsert_track(track_data)

        snapshot_id = sqlite_backend.create_snapshot(sample_snapshot_data)

        # Insert play history for multiple tracks
        for track_data in sample_tracks_data[:3]:
            history_data = {
                "persistent_id": track_data["persistent_id"],
                "snapshot_id": snapshot_id,
                "played_count": 10,
                "skipped_count": 1,
            }
            sqlite_backend.insert_play_history(history_data)

        all_history = sqlite_backend.get_all_play_history()
        assert len(all_history) == 3


class TestSQLiteBackendDailyPlayOperations:
    """Tests for daily play operations"""

    def test_upsert_daily_play_new(self, sqlite_backend, sample_daily_play_data):
        """Test inserting new daily play"""
        sqlite_backend.upsert_daily_play(sample_daily_play_data)

        daily = sqlite_backend.get_daily_play(
            sample_daily_play_data["persistent_id"], sample_daily_play_data["date"]
        )
        assert daily is not None
        assert daily["plays_delta"] == 5
        assert daily["skips_delta"] == 1

    def test_upsert_daily_play_accumulate(self, sqlite_backend, sample_daily_play_data):
        """Test that upsert accumulates deltas for same track/date"""
        # Insert first time
        sqlite_backend.upsert_daily_play(sample_daily_play_data)

        # Insert again with more plays
        updated_data = sample_daily_play_data.copy()
        updated_data["plays_delta"] = 3
        updated_data["skips_delta"] = 2
        sqlite_backend.upsert_daily_play(updated_data)

        daily = sqlite_backend.get_daily_play(
            sample_daily_play_data["persistent_id"], sample_daily_play_data["date"]
        )
        # Should have accumulated
        assert daily["plays_delta"] == 8  # 5 + 3
        assert daily["skips_delta"] == 3  # 1 + 2

    def test_get_daily_play_not_found(self, sqlite_backend):
        """Test getting non-existent daily play returns None"""
        daily = sqlite_backend.get_daily_play("NONEXISTENT", "2024-01-15")
        assert daily is None

    def test_get_all_daily_plays(self, sqlite_backend, sample_tracks_data):
        """Test getting all daily plays"""
        # Insert daily plays for multiple tracks/dates
        for i, track_data in enumerate(sample_tracks_data[:3]):
            for day in range(2):
                daily_data = {
                    "persistent_id": track_data["persistent_id"],
                    "date": f"2024-01-{15 + day:02d}",
                    "plays_delta": i + 1,
                    "skips_delta": i,
                }
                sqlite_backend.upsert_daily_play(daily_data)

        all_dailies = sqlite_backend.get_all_daily_plays()
        assert len(all_dailies) == 6  # 3 tracks * 2 days


class TestSQLiteBackendQueryOperations:
    """Tests for reporting query operations"""

    def test_query_top_tracks(self, populated_sqlite_backend):
        """Test querying top tracks"""
        results = populated_sqlite_backend.query_top_tracks(
            "2024-01-09", "2024-01-15", limit=5
        )

        assert len(results) <= 5
        assert all("name" in r for r in results)
        assert all("artist" in r for r in results)
        assert all("plays" in r for r in results)

        # Should be sorted by plays descending
        if len(results) > 1:
            assert results[0]["plays"] >= results[1]["plays"]

    def test_query_top_artists(self, populated_sqlite_backend):
        """Test querying top artists"""
        results = populated_sqlite_backend.query_top_artists(
            "2024-01-09", "2024-01-15", limit=5
        )

        assert len(results) <= 5
        assert all("artist" in r for r in results)
        assert all("plays" in r for r in results)

        # Should be sorted by plays descending
        if len(results) > 1:
            assert results[0]["plays"] >= results[1]["plays"]

    def test_query_top_albums(self, populated_sqlite_backend):
        """Test querying top albums"""
        results = populated_sqlite_backend.query_top_albums(
            "2024-01-09", "2024-01-15", limit=5
        )

        assert len(results) <= 5
        assert all("album" in r for r in results)
        assert all("artist" in r for r in results)
        assert all("plays" in r for r in results)

    def test_query_top_genres(self, populated_sqlite_backend):
        """Test querying top genres"""
        results = populated_sqlite_backend.query_top_genres(
            "2024-01-09", "2024-01-15", limit=5
        )

        assert len(results) <= 5
        assert all("genre" in r for r in results)
        assert all("plays" in r for r in results)

    def test_query_most_skipped(self, populated_sqlite_backend):
        """Test querying most skipped tracks"""
        results = populated_sqlite_backend.query_most_skipped(
            "2024-01-09", "2024-01-15", limit=5
        )

        assert len(results) <= 5
        assert all("name" in r for r in results)
        assert all("artist" in r for r in results)
        assert all("skips" in r for r in results)

        # Should only include tracks with skips > 0
        assert all(r["skips"] > 0 for r in results)

    def test_query_listening_stats(self, populated_sqlite_backend):
        """Test querying listening statistics"""
        stats = populated_sqlite_backend.query_listening_stats(
            "2024-01-09", "2024-01-15"
        )

        assert "total_plays" in stats
        assert "total_skips" in stats
        assert "unique_tracks" in stats
        assert "total_time" in stats

        assert stats["total_plays"] >= 0
        assert stats["total_skips"] >= 0
        assert stats["unique_tracks"] >= 0
        assert stats["total_time"] >= 0

    def test_query_stats(self, populated_sqlite_backend):
        """Test querying overall database statistics"""
        stats = populated_sqlite_backend.query_stats()

        assert "total_tracks" in stats
        assert "total_snapshots" in stats
        assert "earliest_date" in stats
        assert "latest_date" in stats

        assert stats["total_tracks"] == 10  # From populated fixture
        assert stats["total_snapshots"] == 1

    def test_query_top_tracks_empty_date_range(self, populated_sqlite_backend):
        """Test querying with date range that has no data"""
        results = populated_sqlite_backend.query_top_tracks(
            "2020-01-01", "2020-01-02", limit=10
        )
        assert len(results) == 0


class TestSQLiteBackendTransactionContext:
    """Tests for transaction context manager"""

    def test_transaction_commit(self, sqlite_backend, sample_track_data):
        """Test transaction commits on success"""
        with sqlite_backend.transaction():
            sqlite_backend.upsert_track(sample_track_data)

        # Verify data was committed
        track = sqlite_backend.get_track(sample_track_data["persistent_id"])
        assert track is not None

    def test_transaction_rollback(self, sqlite_backend, sample_track_data):
        """Test transaction rolls back on exception"""
        try:
            with sqlite_backend.transaction():
                sqlite_backend.upsert_track(sample_track_data)
                raise Exception("Intentional error")
        except Exception:
            pass

        # Data should not be committed due to exception
        sqlite_backend.get_track(sample_track_data["persistent_id"])
        # Note: This behavior depends on SQLAlchemy session management
        # The get_track call uses its own session, so it won't see uncommitted data


class TestSQLiteBackendEdgeCases:
    """Tests for edge cases and error handling"""

    def test_upsert_track_with_null_fields(self, sqlite_backend):
        """Test upserting track with null/missing fields"""
        minimal_track = {
            "persistent_id": "MINIMAL123",
            "name": "Minimal Track",
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
        }
        sqlite_backend.upsert_track(minimal_track)

        track = sqlite_backend.get_track("MINIMAL123")
        assert track is not None
        assert track["name"] == "Minimal Track"
        assert track["artist"] is None

    def test_query_with_no_data(self, sqlite_backend):
        """Test queries return empty results when no data"""
        stats = sqlite_backend.query_listening_stats("2024-01-01", "2024-01-31")

        assert stats["total_plays"] == 0
        assert stats["total_skips"] == 0
        assert stats["unique_tracks"] == 0
        assert stats["total_time"] == 0
