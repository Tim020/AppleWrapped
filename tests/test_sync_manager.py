#!/usr/bin/env python3
"""
Tests for sync manager with SQLite to Couchbase sync
"""

import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.database.sync_manager import SyncManager


@pytest.fixture
def mock_sqlite_backend():
    """Mock SQLite backend"""
    backend = Mock()
    backend.get_all_snapshots.return_value = []
    backend.get_play_history_for_snapshot.return_value = []
    backend.get_track.return_value = None
    backend.get_daily_play.return_value = None
    return backend


@pytest.fixture
def mock_couchbase_backend():
    """Mock Couchbase backend"""
    backend = Mock()
    backend.get_all_snapshots.return_value = []
    backend.get_track.return_value = None
    backend.get_play_history_for_snapshot.return_value = []
    backend.get_daily_play.return_value = None
    backend.collections = {
        'snapshots': Mock(),
        'counters': Mock()
    }
    return backend


@pytest.fixture
def temp_state_file(tmp_path):
    """Temporary sync state file"""
    state_file = tmp_path / "sync_state.json"
    return str(state_file)


class TestSyncManagerStateManagement:
    """Tests for sync state file management"""

    def test_load_nonexistent_state_file(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test loading when state file doesn't exist"""
        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)

        assert manager.sync_state['last_synced_snapshot_id'] == 0
        assert manager.sync_state['last_sync_timestamp'] is None
        assert manager.sync_state['last_sync_status'] is None

    def test_load_existing_state_file(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test loading existing state file"""
        # Create state file
        state_data = {
            'last_synced_snapshot_id': 5,
            'last_sync_timestamp': '2024-01-15T12:00:00',
            'last_sync_status': 'success'
        }
        with open(temp_state_file, 'w') as f:
            json.dump(state_data, f)

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)

        assert manager.sync_state['last_synced_snapshot_id'] == 5
        assert manager.sync_state['last_sync_timestamp'] == '2024-01-15T12:00:00'
        assert manager.sync_state['last_sync_status'] == 'success'

    def test_save_state_file(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test saving state file"""
        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)

        manager.sync_state['last_synced_snapshot_id'] = 10
        manager.sync_state['last_sync_timestamp'] = '2024-01-20T10:00:00'
        manager.sync_state['last_sync_status'] = 'success'
        manager._save_sync_state()

        # Verify file was written
        with open(temp_state_file, 'r') as f:
            saved_state = json.load(f)

        assert saved_state['last_synced_snapshot_id'] == 10
        assert saved_state['last_sync_timestamp'] == '2024-01-20T10:00:00'

    def test_load_corrupted_state_file(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test loading corrupted state file falls back to defaults"""
        # Write invalid JSON
        with open(temp_state_file, 'w') as f:
            f.write("invalid json {")

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)

        # Should fall back to defaults
        assert manager.sync_state['last_synced_snapshot_id'] == 0


class TestSyncManagerNeedsSync:
    """Tests for checking if sync is needed"""

    def test_needs_sync_when_new_snapshots_exist(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test needs_sync returns True when there are new snapshots"""
        mock_sqlite_backend.get_all_snapshots.return_value = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
            {'snapshot_id': 3, 'timestamp': '2024-01-03'},
        ]

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager.sync_state['last_synced_snapshot_id'] = 1

        assert manager.needs_sync() is True

    def test_needs_sync_when_no_new_snapshots(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test needs_sync returns False when no new snapshots"""
        mock_sqlite_backend.get_all_snapshots.return_value = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
        ]

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager.sync_state['last_synced_snapshot_id'] = 2

        assert manager.needs_sync() is False

    def test_needs_sync_when_no_snapshots(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test needs_sync returns False when no snapshots exist"""
        mock_sqlite_backend.get_all_snapshots.return_value = []

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)

        assert manager.needs_sync() is False


class TestSyncManagerSync:
    """Tests for sync operations"""

    def test_sync_single_snapshot(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing a single snapshot"""
        # Setup snapshots
        snapshot = {'snapshot_id': 1, 'timestamp': '2024-01-01', 'total_tracks': 10}
        mock_sqlite_backend.get_all_snapshots.return_value = [snapshot]

        # Setup play history
        play_history = [
            {
                'snapshot_id': 1,
                'persistent_id': 'track1',
                'played_count': 5,
                'played_date': '2024-01-01'
            }
        ]
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = play_history

        # Setup track
        track = {'persistent_id': 'track1', 'name': 'Test Track', 'last_seen': '2024-01-01'}
        mock_sqlite_backend.get_track.return_value = track

        # Setup daily play
        daily_play = {'persistent_id': 'track1', 'date': '2024-01-01', 'plays_delta': 5}
        mock_sqlite_backend.get_daily_play.return_value = daily_play

        # Mock Couchbase returns (nothing exists)
        mock_couchbase_backend.get_track.return_value = None
        mock_couchbase_backend.get_all_snapshots.return_value = []
        mock_couchbase_backend.get_play_history_for_snapshot.return_value = []
        mock_couchbase_backend.get_daily_play.return_value = None

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result = manager.sync()

        assert result is True
        assert manager.sync_state['last_synced_snapshot_id'] == 1
        assert manager.sync_state['last_sync_status'] == 'success'

        # Verify upsert calls
        mock_couchbase_backend.upsert_track.assert_called_once()
        mock_couchbase_backend.insert_play_history.assert_called_once()
        mock_couchbase_backend.upsert_daily_play.assert_called_once()

    def test_sync_multiple_snapshots(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing multiple snapshots"""
        snapshots = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
            {'snapshot_id': 3, 'timestamp': '2024-01-03'},
        ]
        mock_sqlite_backend.get_all_snapshots.return_value = snapshots

        # Mock play history returns empty for simplicity
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = []
        mock_couchbase_backend.get_all_snapshots.return_value = []

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result = manager.sync()

        assert result is True
        assert manager.sync_state['last_synced_snapshot_id'] == 3

    def test_sync_incremental_only_new_snapshots(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test incremental sync only syncs new snapshots"""
        snapshots = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
            {'snapshot_id': 3, 'timestamp': '2024-01-03'},
        ]
        mock_sqlite_backend.get_all_snapshots.return_value = snapshots
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = []
        mock_couchbase_backend.get_all_snapshots.return_value = []

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager.sync_state['last_synced_snapshot_id'] = 1

        result = manager.sync()

        assert result is True
        assert manager.sync_state['last_synced_snapshot_id'] == 3

        # Should only query for snapshots 2 and 3
        assert mock_sqlite_backend.get_play_history_for_snapshot.call_count == 2

    def test_sync_no_snapshots_to_sync(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test sync when no snapshots need syncing"""
        mock_sqlite_backend.get_all_snapshots.return_value = []

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result = manager.sync()

        assert result is True

    def test_sync_failure_updates_state(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test sync failure is recorded in state"""
        snapshots = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
        ]
        mock_sqlite_backend.get_all_snapshots.return_value = snapshots
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = []
        mock_couchbase_backend.get_all_snapshots.return_value = []

        # Make Couchbase fail when upserting snapshot 2
        def fail_on_snapshot_2(snapshot_id, *args):
            if snapshot_id == '2':
                raise Exception("Connection lost")

        mock_couchbase_backend.collections['snapshots'].upsert.side_effect = fail_on_snapshot_2

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result = manager.sync()

        assert result is False
        assert manager.sync_state['last_synced_snapshot_id'] == 1  # Only first snapshot succeeded
        assert 'failed' in manager.sync_state['last_sync_status']

    def test_sync_resumes_from_last_successful(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test sync resumes from last successful snapshot after failure"""
        # First sync: fail at snapshot 2
        snapshots = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
        ]
        mock_sqlite_backend.get_all_snapshots.return_value = snapshots
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = []
        mock_couchbase_backend.get_all_snapshots.return_value = []

        # Make first sync fail on snapshot 2
        def fail_on_snapshot_2_first_time(snapshot_id, *args):
            if snapshot_id == '2':
                raise Exception("Connection lost")

        mock_couchbase_backend.collections['snapshots'].upsert.side_effect = fail_on_snapshot_2_first_time

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result = manager.sync()

        assert result is False
        assert manager.sync_state['last_synced_snapshot_id'] == 1

        # Second sync: clear the side_effect so snapshot 2 succeeds
        mock_couchbase_backend.collections['snapshots'].upsert.side_effect = None

        result = manager.sync()

        assert result is True
        assert manager.sync_state['last_synced_snapshot_id'] == 2


class TestSyncManagerTrackSync:
    """Tests for track syncing logic"""

    def test_sync_track_new_track(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing a new track that doesn't exist in Couchbase"""
        track = {'persistent_id': 'track1', 'name': 'Test', 'last_seen': '2024-01-01'}
        mock_couchbase_backend.get_track.return_value = None

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager._sync_track(track)

        mock_couchbase_backend.upsert_track.assert_called_once_with(track)

    def test_sync_track_newer_version(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing a track with newer last_seen timestamp"""
        track = {'persistent_id': 'track1', 'name': 'Test', 'last_seen': '2024-01-15'}
        existing = {'persistent_id': 'track1', 'name': 'Test', 'last_seen': '2024-01-10'}

        mock_couchbase_backend.get_track.return_value = existing

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager._sync_track(track)

        # Should upsert because SQLite version is newer
        mock_couchbase_backend.upsert_track.assert_called_once_with(track)

    def test_sync_track_older_version(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing a track with older last_seen timestamp"""
        track = {'persistent_id': 'track1', 'name': 'Test', 'last_seen': '2024-01-10'}
        existing = {'persistent_id': 'track1', 'name': 'Test', 'last_seen': '2024-01-15'}

        mock_couchbase_backend.get_track.return_value = existing

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager._sync_track(track)

        # Should NOT upsert because Couchbase version is newer
        mock_couchbase_backend.upsert_track.assert_not_called()


class TestSyncManagerDailyPlaySync:
    """Tests for daily play syncing logic"""

    def test_sync_daily_play_new(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing new daily play that doesn't exist"""
        daily_play = {'persistent_id': 'track1', 'date': '2024-01-01', 'plays_delta': 5, 'skips_delta': 1}
        mock_couchbase_backend.get_daily_play.return_value = None

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager._sync_daily_play(daily_play)

        mock_couchbase_backend.upsert_daily_play.assert_called_once_with(daily_play)

    def test_sync_daily_play_merge(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing daily play merges deltas when already exists"""
        daily_play = {'persistent_id': 'track1', 'date': '2024-01-01', 'plays_delta': 5, 'skips_delta': 1}
        existing = {'persistent_id': 'track1', 'date': '2024-01-01', 'plays_delta': 3, 'skips_delta': 2}

        mock_couchbase_backend.get_daily_play.return_value = existing

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager._sync_daily_play(daily_play)

        # Should merge and update
        expected_merged = {'persistent_id': 'track1', 'date': '2024-01-01', 'plays_delta': 8, 'skips_delta': 3}
        mock_couchbase_backend.upsert_daily_play.assert_called_once_with(expected_merged)


class TestSyncManagerIdempotence:
    """Tests for idempotent sync operations"""

    def test_sync_same_data_twice(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test syncing same data twice is idempotent"""
        snapshot = {'snapshot_id': 1, 'timestamp': '2024-01-01'}
        mock_sqlite_backend.get_all_snapshots.return_value = [snapshot]
        mock_sqlite_backend.get_play_history_for_snapshot.return_value = []

        # First sync
        mock_couchbase_backend.get_all_snapshots.return_value = []
        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        result1 = manager.sync()

        assert result1 is True
        assert manager.sync_state['last_synced_snapshot_id'] == 1

        # Second sync (no new data)
        result2 = manager.sync()

        assert result2 is True
        # State should remain the same
        assert manager.sync_state['last_synced_snapshot_id'] == 1


class TestSyncManagerStatus:
    """Tests for sync status reporting"""

    def test_get_sync_status(self, mock_sqlite_backend, mock_couchbase_backend, temp_state_file):
        """Test getting sync status"""
        mock_sqlite_backend.get_all_snapshots.return_value = [
            {'snapshot_id': 1, 'timestamp': '2024-01-01'},
            {'snapshot_id': 2, 'timestamp': '2024-01-02'},
        ]

        manager = SyncManager(mock_sqlite_backend, mock_couchbase_backend, temp_state_file)
        manager.sync_state['last_synced_snapshot_id'] = 1
        manager.sync_state['last_sync_timestamp'] = '2024-01-01T12:00:00'
        manager.sync_state['last_sync_status'] = 'success'

        status = manager.get_sync_status()

        assert status['last_synced_snapshot_id'] == 1
        assert status['last_sync_timestamp'] == '2024-01-01T12:00:00'
        assert status['last_sync_status'] == 'success'
        assert status['needs_sync'] is True  # Because snapshot 2 is unsynced
