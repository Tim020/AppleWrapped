#!/usr/bin/env python3
"""
Tests for configuration management
"""

import os
import pytest
from app.config import CouchbaseConfig


class TestCouchbaseConfig:
    """Tests for CouchbaseConfig class"""

    def test_default_values(self):
        """Test default configuration values"""
        config = CouchbaseConfig()

        assert config.host is None
        assert config.port == 8091
        assert config.username == ""
        assert config.password == ""
        assert config.bucket_name == "apple_wrapped"
        assert config.scope_name == "_default"
        assert config.tracks_collection == "tracks"
        assert config.snapshots_collection == "snapshots"
        assert config.playhistory_collection == "playhistory"
        assert config.dailyplays_collection == "dailyplays"
        assert config.counters_collection == "counters"

    def test_custom_values(self):
        """Test creating config with custom values"""
        config = CouchbaseConfig(
            host="192.168.1.100",
            port=9000,
            username="admin",
            password="secret"
        )

        assert config.host == "192.168.1.100"
        assert config.port == 9000
        assert config.username == "admin"
        assert config.password == "secret"

    def test_is_configured_no_host(self):
        """Test is_configured returns False when no host"""
        config = CouchbaseConfig()
        assert not config.is_configured()

    def test_is_configured_empty_host(self):
        """Test is_configured returns False when host is empty string"""
        config = CouchbaseConfig(host="")
        assert not config.is_configured()

    def test_is_configured_with_host(self):
        """Test is_configured returns True when host is set"""
        config = CouchbaseConfig(host="192.168.1.100")
        assert config.is_configured()

    def test_get_connection_string_without_host(self):
        """Test get_connection_string raises error without host"""
        config = CouchbaseConfig()

        with pytest.raises(ValueError, match="Couchbase host not configured"):
            config.get_connection_string()

    def test_get_connection_string_with_host(self):
        """Test get_connection_string returns correct format"""
        config = CouchbaseConfig(host="192.168.1.100")

        conn_str = config.get_connection_string()
        assert conn_str == "couchbase://192.168.1.100"

    def test_from_args_and_env_cli_priority(self, mock_args, monkeypatch):
        """Test CLI arguments take priority over environment variables"""
        # Set environment variables
        monkeypatch.setenv('COUCHBASE_HOST', 'env-host')
        monkeypatch.setenv('COUCHBASE_PORT', '9000')
        monkeypatch.setenv('COUCHBASE_USERNAME', 'env-user')
        monkeypatch.setenv('COUCHBASE_PASSWORD', 'env-pass')

        # Set CLI args to override
        mock_args.couchbase_host = 'cli-host'
        mock_args.couchbase_port = 8091
        mock_args.couchbase_username = 'cli-user'
        mock_args.couchbase_password = 'cli-pass'

        config = CouchbaseConfig.from_args_and_env(mock_args)

        # CLI args should take priority
        assert config.host == 'cli-host'
        assert config.port == 8091
        assert config.username == 'cli-user'
        assert config.password == 'cli-pass'

    def test_from_args_and_env_fallback_to_env(self, mock_args, monkeypatch):
        """Test falls back to environment variables when CLI args not provided"""
        # Set environment variables
        monkeypatch.setenv('COUCHBASE_HOST', 'env-host')
        monkeypatch.setenv('COUCHBASE_PORT', '9000')
        monkeypatch.setenv('COUCHBASE_USERNAME', 'env-user')
        monkeypatch.setenv('COUCHBASE_PASSWORD', 'env-pass')

        # CLI args are None/empty
        mock_args.couchbase_host = None
        mock_args.couchbase_port = None
        mock_args.couchbase_username = None
        mock_args.couchbase_password = None

        config = CouchbaseConfig.from_args_and_env(mock_args)

        # Should use environment variables
        assert config.host == 'env-host'
        assert config.port == 9000
        assert config.username == 'env-user'
        assert config.password == 'env-pass'

    def test_from_args_and_env_defaults(self, mock_args):
        """Test uses defaults when neither CLI nor env provided"""
        # No CLI args, no env vars
        config = CouchbaseConfig.from_args_and_env(mock_args)

        assert config.host is None
        assert config.port == 8091
        assert config.username == ""
        assert config.password == ""

    def test_from_args_and_env_mixed_sources(self, mock_args, monkeypatch):
        """Test using mixed sources (some CLI, some env, some default)"""
        # Only set host in environment
        monkeypatch.setenv('COUCHBASE_HOST', 'env-host')
        monkeypatch.setenv('COUCHBASE_USERNAME', 'env-user')

        # Only set port in CLI
        mock_args.couchbase_host = None
        mock_args.couchbase_port = 9000
        mock_args.couchbase_username = None
        mock_args.couchbase_password = None

        config = CouchbaseConfig.from_args_and_env(mock_args)

        assert config.host == 'env-host'  # From env
        assert config.port == 9000        # From CLI
        assert config.username == 'env-user'  # From env
        assert config.password == ""      # Default
