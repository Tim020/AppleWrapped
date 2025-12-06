#!/usr/bin/env python3
"""
Tests for backend manager with automatic failover
"""

import pytest
from unittest.mock import patch
from datetime import datetime

from app.database.backend_manager import BackendManager
from app.config import CouchbaseConfig


@pytest.fixture
def mock_couchbase_config():
    """Mock Couchbase configuration"""
    config = CouchbaseConfig(
        host="192.168.1.100", port=8091, username="admin", password="password"
    )
    return config


@pytest.fixture
def mock_couchbase_config_not_configured():
    """Mock Couchbase configuration without host"""
    return CouchbaseConfig()


class TestBackendManagerConnection:
    """Tests for connection management and backend selection"""

    def test_connect_couchbase_success(self, temp_db_path, mock_couchbase_config):
        """Test successful connection to Couchbase"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        # Mock the CouchbaseBackend to succeed
        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = True

            result = manager.connect()

            assert result is True
            assert manager.is_using_couchbase()
            assert not manager.is_using_sqlite()
            MockCouchbase.assert_called_once_with(mock_couchbase_config)

    def test_connect_couchbase_fails_fallback_sqlite(
        self, temp_db_path, mock_couchbase_config
    ):
        """Test fallback to SQLite when Couchbase fails"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        # Mock CouchbaseBackend to fail
        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = False

            result = manager.connect()

            assert result is True
            assert manager.is_using_sqlite()
            assert not manager.is_using_couchbase()

    def test_connect_couchbase_not_configured_uses_sqlite(
        self, temp_db_path, mock_couchbase_config_not_configured
    ):
        """Test uses SQLite when Couchbase not configured"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)

        result = manager.connect()

        assert result is True
        assert manager.is_using_sqlite()
        assert not manager.is_using_couchbase()

    def test_connect_force_sqlite_environment(
        self, temp_db_path, mock_couchbase_config, monkeypatch
    ):
        """Test FORCE_SQLITE environment variable"""
        monkeypatch.setenv("FORCE_SQLITE", "1")

        manager = BackendManager(temp_db_path, mock_couchbase_config)
        result = manager.connect()

        assert result is True
        assert manager.is_using_sqlite()
        # Should not have even attempted Couchbase

    def test_is_healthy_when_connected(
        self, temp_db_path, mock_couchbase_config_not_configured
    ):
        """Test health check when connected"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        assert manager.is_healthy()

    def test_is_healthy_when_not_connected(
        self, temp_db_path, mock_couchbase_config_not_configured
    ):
        """Test health check when not connected"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)

        assert not manager.is_healthy()

    def test_disconnect(self, temp_db_path, mock_couchbase_config_not_configured):
        """Test disconnect closes backends"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        manager.disconnect()

        assert not manager._connected
        assert manager.active_backend is None


class TestBackendManagerReconnect:
    """Tests for Couchbase reconnection attempts"""

    def test_try_reconnect_couchbase_from_sqlite(
        self, temp_db_path, mock_couchbase_config
    ):
        """Test successful reconnect to Couchbase from SQLite"""
        # Start with SQLite
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        # Mock Couchbase to fail first, succeed later
        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = False

            # Initial connect - should use SQLite
            manager.connect()
            assert manager.is_using_sqlite()

            # Now update the same mock to succeed on next connect attempt
            mock_cb.connect.return_value = True

            # Try reconnect
            result = manager.try_reconnect_couchbase()

            assert result is True
            assert manager.is_using_couchbase()

    def test_try_reconnect_when_already_using_couchbase(
        self, temp_db_path, mock_couchbase_config
    ):
        """Test reconnect does nothing when already using Couchbase"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = True

            manager.connect()
            assert manager.is_using_couchbase()

            # Try reconnect - should do nothing
            result = manager.try_reconnect_couchbase()
            assert result is False

    def test_try_reconnect_when_force_sqlite(
        self, temp_db_path, mock_couchbase_config, monkeypatch
    ):
        """Test reconnect respects FORCE_SQLITE"""
        monkeypatch.setenv("FORCE_SQLITE", "1")

        manager = BackendManager(temp_db_path, mock_couchbase_config)
        manager.connect()

        result = manager.try_reconnect_couchbase()
        assert result is False

    def test_try_reconnect_fails_stays_on_sqlite(
        self, temp_db_path, mock_couchbase_config
    ):
        """Test stays on SQLite when reconnect fails"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        # Start with SQLite
        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = False

            manager.connect()
            assert manager.is_using_sqlite()

            # Try reconnect - still fails
            result = manager.try_reconnect_couchbase()

            assert result is False
            assert manager.is_using_sqlite()


class TestBackendManagerFailover:
    """Tests for automatic failover on operation failures"""

    def test_failover_on_upsert_track_failure(
        self, temp_db_path, mock_couchbase_config, sample_track_data
    ):
        """Test automatic failover when upsert_track fails"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            # Setup successful connection
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = True

            # Mock upsert_track to fail
            mock_cb.upsert_track.side_effect = Exception("Connection lost")

            manager.connect()
            assert manager.is_using_couchbase()

            # This should trigger failover and retry on SQLite
            manager.upsert_track(sample_track_data)

            # Should have failed over to SQLite
            assert manager.is_using_sqlite()

            # Verify data is in SQLite
            track = manager.get_track(sample_track_data["persistent_id"])
            assert track is not None

    def test_failover_on_create_snapshot_failure(
        self, temp_db_path, mock_couchbase_config, sample_snapshot_data
    ):
        """Test automatic failover when create_snapshot fails"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = True
            mock_cb.create_snapshot.side_effect = Exception("Connection lost")

            manager.connect()
            assert manager.is_using_couchbase()

            # Should failover and succeed
            snapshot_id = manager.create_snapshot(sample_snapshot_data)

            assert snapshot_id is not None
            assert manager.is_using_sqlite()

    def test_no_failover_when_already_on_sqlite(
        self, temp_db_path, mock_couchbase_config_not_configured, sample_track_data
    ):
        """Test exception propagates when already on SQLite"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        assert manager.is_using_sqlite()

        # Insert invalid data to cause error
        invalid_track = {"name": "Missing persistent_id"}

        with pytest.raises(Exception):
            manager.upsert_track(invalid_track)


class TestBackendManagerOperationDelegation:
    """Tests for operation delegation to active backend"""

    def test_operations_require_active_backend(
        self, temp_db_path, mock_couchbase_config_not_configured
    ):
        """Test operations fail without active backend"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        # Don't connect

        with pytest.raises(RuntimeError, match="No active backend available"):
            manager.get_track("test")

        with pytest.raises(RuntimeError, match="No active backend available"):
            manager.query_stats()

    def test_get_track_delegates(
        self, temp_db_path, mock_couchbase_config_not_configured, sample_track_data
    ):
        """Test get_track delegates to active backend"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        # Insert track
        manager.upsert_track(sample_track_data)

        # Get track
        track = manager.get_track(sample_track_data["persistent_id"])

        assert track is not None
        assert track["name"] == sample_track_data["name"]

    def test_query_operations_delegate(
        self, temp_db_path, mock_couchbase_config_not_configured
    ):
        """Test query operations delegate to active backend"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        # These should not raise errors
        stats = manager.query_stats()
        assert stats is not None

        top_tracks = manager.query_top_tracks("2024-01-01", "2024-01-31", 10)
        assert isinstance(top_tracks, list)

    def test_transaction_context_delegates(
        self, temp_db_path, mock_couchbase_config_not_configured, sample_track_data
    ):
        """Test transaction context delegates to active backend"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        with manager.transaction():
            manager.upsert_track(sample_track_data)

        # Verify committed
        track = manager.get_track(sample_track_data["persistent_id"])
        assert track is not None


class TestBackendManagerIntegration:
    """Integration tests for backend manager"""

    def test_full_workflow_with_sqlite(
        self, temp_db_path, mock_couchbase_config_not_configured, sample_tracks_data
    ):
        """Test complete workflow using SQLite backend"""
        manager = BackendManager(temp_db_path, mock_couchbase_config_not_configured)
        manager.connect()

        # Insert tracks
        for track_data in sample_tracks_data:
            manager.upsert_track(track_data)

        # Create snapshot
        snapshot_data = {
            "timestamp": datetime.now().isoformat(),
            "total_tracks": len(sample_tracks_data),
            "collection_duration_seconds": 60.0,
        }
        manager.create_snapshot(snapshot_data)

        # Query stats
        stats = manager.query_stats()
        assert stats["total_tracks"] == len(sample_tracks_data)
        assert stats["total_snapshots"] == 1

    def test_backend_state_checks(self, temp_db_path, mock_couchbase_config):
        """Test backend state checking methods"""
        manager = BackendManager(temp_db_path, mock_couchbase_config)

        # Initially not using either
        assert not manager.is_using_couchbase()
        assert not manager.is_using_sqlite()

        # After connecting without Couchbase available
        with patch("app.database.backend_manager.CouchbaseBackend") as MockCouchbase:
            mock_cb = MockCouchbase.return_value
            mock_cb.connect.return_value = False

            manager.connect()

            assert not manager.is_using_couchbase()
            assert manager.is_using_sqlite()
