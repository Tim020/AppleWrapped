#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures
"""

import pytest
from datetime import datetime, timedelta

from app.database.sqlite_backend import SQLiteBackend
from app import models


@pytest.fixture(autouse=True)
def reset_database_globals():
    """Reset the global database state before each test to ensure isolation"""
    # Reset the module-level singletons in models.py
    models._engine = None
    models._SessionFactory = None
    yield
    # Cleanup after test - properly dispose of engine to close connections
    if models._engine is not None:
        models._engine.dispose()
    models._engine = None
    models._SessionFactory = None


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file that is cleaned up after test"""
    db_file = tmp_path / "test.db"
    yield str(db_file)

    # Cleanup handled automatically by tmp_path fixture


@pytest.fixture
def sqlite_backend(temp_db_path):
    """Create a fresh SQLite backend for each test"""
    backend = SQLiteBackend(temp_db_path)
    backend.connect()

    yield backend

    backend.disconnect()


@pytest.fixture
def sample_track_data():
    """Sample track data for testing"""
    return {
        'persistent_id': 'ABC123456789ABCD',
        'name': 'Test Song',
        'artist': 'Test Artist',
        'album': 'Test Album',
        'album_artist': 'Test Artist',
        'genre': 'Rock',
        'year': 2023,
        'duration': 245.5,
        'track_number': 1,
        'disc_number': 1,
        'date_added': '2023-01-01',
        'location': '/Music/test.mp3',
        'first_seen': datetime.now().isoformat(),
        'last_seen': datetime.now().isoformat()
    }


@pytest.fixture
def sample_tracks_data():
    """Multiple sample tracks for testing"""
    base_time = datetime.now()
    return [
        {
            'persistent_id': f'TRACK{i:016X}',
            'name': f'Song {i}',
            'artist': f'Artist {i % 3}',  # 3 different artists
            'album': f'Album {i % 2}',    # 2 different albums
            'album_artist': f'Artist {i % 3}',
            'genre': ['Rock', 'Pop', 'Jazz'][i % 3],
            'year': 2020 + (i % 4),
            'duration': 180.0 + (i * 10),
            'track_number': (i % 12) + 1,
            'disc_number': 1,
            'date_added': '2023-01-01',
            'location': f'/Music/song{i}.mp3',
            'first_seen': base_time.isoformat(),
            'last_seen': base_time.isoformat()
        }
        for i in range(10)
    ]


@pytest.fixture
def sample_snapshot_data():
    """Sample snapshot data for testing"""
    return {
        'timestamp': datetime.now().isoformat(),
        'total_tracks': 100,
        'collection_duration_seconds': 120.5,
        'notes': 'Test snapshot'
    }


@pytest.fixture
def sample_play_history_data():
    """Sample play history data for testing"""
    return {
        'persistent_id': 'ABC123456789ABCD',
        'snapshot_id': 1,
        'played_count': 42,
        'skipped_count': 3,
        'played_date': '2024-01-15',
        'rating': 80
    }


@pytest.fixture
def sample_daily_play_data():
    """Sample daily play data for testing"""
    return {
        'persistent_id': 'ABC123456789ABCD',
        'date': '2024-01-15',
        'plays_delta': 5,
        'skips_delta': 1
    }


@pytest.fixture
def populated_sqlite_backend(sqlite_backend, sample_tracks_data):
    """SQLite backend with sample data already populated"""
    # Insert tracks
    for track_data in sample_tracks_data:
        sqlite_backend.upsert_track(track_data)

    # Create a snapshot
    snapshot_data = {
        'timestamp': datetime.now().isoformat(),
        'total_tracks': len(sample_tracks_data),
        'collection_duration_seconds': 60.0
    }
    snapshot_id = sqlite_backend.create_snapshot(snapshot_data)

    # Add play history for each track
    for i, track_data in enumerate(sample_tracks_data):
        history_data = {
            'persistent_id': track_data['persistent_id'],
            'snapshot_id': snapshot_id,
            'played_count': (i + 1) * 5,  # Varying play counts
            'skipped_count': i,
            'played_date': '2024-01-15',
            'rating': (i % 5) * 20  # Ratings 0, 20, 40, 60, 80
        }
        sqlite_backend.insert_play_history(history_data)

    # Add daily plays for the past 7 days
    base_date = datetime(2024, 1, 15)
    for day_offset in range(7):
        current_date = (base_date - timedelta(days=day_offset)).strftime('%Y-%m-%d')
        for i, track_data in enumerate(sample_tracks_data):
            # Not all tracks played every day
            if (i + day_offset) % 3 == 0:
                daily_data = {
                    'persistent_id': track_data['persistent_id'],
                    'date': current_date,
                    'plays_delta': (i % 5) + 1,
                    'skips_delta': i % 3
                }
                sqlite_backend.upsert_daily_play(daily_data)

    return sqlite_backend


@pytest.fixture
def mock_args():
    """Mock command line arguments for testing config"""
    class MockArgs:
        couchbase_host = None
        couchbase_port = 8091
        couchbase_username = ''
        couchbase_password = ''

    return MockArgs()
