#!/usr/bin/env python3
"""
SQLite backend implementation wrapping existing SQLAlchemy models
"""

from contextlib import contextmanager
from typing import Optional, Dict, List
from datetime import datetime

from sqlalchemy import func, select

from app.database.abstract_backend import DatabaseBackend
from app.models import (
    Track,
    Snapshot,
    PlayHistory,
    DailyPlay,
    init_database,
    get_session_context,
)
from app.logging_config import logger


class SQLiteBackend(DatabaseBackend):
    """SQLite implementation of the database backend"""

    def __init__(self, db_path: str):
        """
        Initialize SQLite backend

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connected = False

    def connect(self) -> bool:
        """Connect to SQLite database"""
        try:
            init_database(self.db_path)
            self._connected = True
            logger.info("sqlite_backend_connected", db_path=str(self.db_path))
            return True
        except Exception as e:
            logger.error(
                "sqlite_backend_connection_failed",
                db_path=str(self.db_path),
                error=str(e),
            )
            self._connected = False
            return False

    def is_healthy(self) -> bool:
        """Check if SQLite backend is healthy"""
        if not self._connected:
            return False

        try:
            # Quick health check query
            with get_session_context() as session:
                session.scalar(select(func.count(Track.persistent_id)))
            return True
        except Exception as e:
            logger.warning("sqlite_backend_health_check_failed", error=str(e))
            return False

    def disconnect(self):
        """Disconnect from SQLite (no-op for SQLite)"""
        self._connected = False
        logger.debug("sqlite_backend_disconnected")

    @contextmanager
    def transaction(self):
        """Context manager for transactions"""
        with get_session_context() as session:
            yield session

    # Track Operations

    def get_track(self, persistent_id: str) -> Optional[Dict]:
        """Get a track by persistent_id"""
        with get_session_context() as session:
            stmt = select(Track).where(Track.persistent_id == persistent_id)
            track = session.scalar(stmt)

            if track:
                return {
                    "persistent_id": track.persistent_id,
                    "name": track.name,
                    "artist": track.artist,
                    "album": track.album,
                    "album_artist": track.album_artist,
                    "genre": track.genre,
                    "year": track.year,
                    "duration": track.duration,
                    "track_number": track.track_number,
                    "disc_number": track.disc_number,
                    "date_added": track.date_added,
                    "location": track.location,
                    "first_seen": track.first_seen.isoformat()
                    if track.first_seen
                    else None,
                    "last_seen": track.last_seen.isoformat()
                    if track.last_seen
                    else None,
                }
            return None

    def upsert_track(self, track_data: Dict):
        """Insert or update a track"""
        with get_session_context() as session:
            persistent_id = track_data["persistent_id"]
            stmt = select(Track).where(Track.persistent_id == persistent_id)
            track = session.scalar(stmt)

            timestamp = datetime.fromisoformat(
                track_data.get("last_seen", datetime.now().isoformat())
            )

            if track:
                # Update existing
                track.name = track_data.get("name")
                track.artist = track_data.get("artist")
                track.album = track_data.get("album")
                track.album_artist = track_data.get("album_artist")
                track.genre = track_data.get("genre")
                track.year = track_data.get("year")
                track.duration = track_data.get("duration")
                track.track_number = track_data.get("track_number")
                track.disc_number = track_data.get("disc_number")
                track.location = track_data.get("location")
                track.last_seen = timestamp
            else:
                # Insert new
                first_seen = datetime.fromisoformat(
                    track_data.get("first_seen", timestamp.isoformat())
                )
                track = Track(
                    persistent_id=persistent_id,
                    name=track_data.get("name"),
                    artist=track_data.get("artist"),
                    album=track_data.get("album"),
                    album_artist=track_data.get("album_artist"),
                    genre=track_data.get("genre"),
                    year=track_data.get("year"),
                    duration=track_data.get("duration"),
                    track_number=track_data.get("track_number"),
                    disc_number=track_data.get("disc_number"),
                    date_added=track_data.get("date_added"),
                    location=track_data.get("location"),
                    first_seen=first_seen,
                    last_seen=timestamp,
                )
                session.add(track)

    def get_all_tracks(self) -> List[Dict]:
        """Get all tracks"""
        with get_session_context() as session:
            stmt = select(Track)
            tracks = session.scalars(stmt).all()

            return [
                {
                    "persistent_id": t.persistent_id,
                    "name": t.name,
                    "artist": t.artist,
                    "album": t.album,
                    "album_artist": t.album_artist,
                    "genre": t.genre,
                    "year": t.year,
                    "duration": t.duration,
                    "track_number": t.track_number,
                    "disc_number": t.disc_number,
                    "date_added": t.date_added,
                    "location": t.location,
                    "first_seen": t.first_seen.isoformat() if t.first_seen else None,
                    "last_seen": t.last_seen.isoformat() if t.last_seen else None,
                }
                for t in tracks
            ]

    # Snapshot Operations

    def create_snapshot(self, snapshot_data: Dict) -> int:
        """Create a new snapshot"""
        with get_session_context() as session:
            timestamp = datetime.fromisoformat(snapshot_data["timestamp"])
            snapshot = Snapshot(
                timestamp=timestamp,
                total_tracks=snapshot_data["total_tracks"],
                collection_duration_seconds=snapshot_data.get(
                    "collection_duration_seconds"
                ),
                notes=snapshot_data.get("notes"),
            )
            session.add(snapshot)
            session.flush()
            return snapshot.snapshot_id

    def get_previous_snapshot(self, before_timestamp: str) -> Optional[Dict]:
        """Get the most recent snapshot before a given timestamp"""
        with get_session_context() as session:
            timestamp = datetime.fromisoformat(before_timestamp)
            stmt = (
                select(Snapshot)
                .where(Snapshot.timestamp < timestamp)
                .order_by(Snapshot.timestamp.desc())
                .limit(1)
            )
            snapshot = session.scalar(stmt)

            if snapshot:
                return {
                    "snapshot_id": snapshot.snapshot_id,
                    "timestamp": snapshot.timestamp.isoformat(),
                    "total_tracks": snapshot.total_tracks,
                    "collection_duration_seconds": snapshot.collection_duration_seconds,
                }
            return None

    def get_all_snapshots(self) -> List[Dict]:
        """Get all snapshots"""
        with get_session_context() as session:
            stmt = select(Snapshot).order_by(Snapshot.snapshot_id)
            snapshots = session.scalars(stmt).all()

            return [
                {
                    "snapshot_id": s.snapshot_id,
                    "timestamp": s.timestamp.isoformat(),
                    "total_tracks": s.total_tracks,
                    "collection_duration_seconds": s.collection_duration_seconds,
                    "notes": s.notes,
                }
                for s in snapshots
            ]

    # PlayHistory Operations

    def get_play_history_for_snapshot(self, snapshot_id: int) -> List[Dict]:
        """Get all play history records for a snapshot"""
        with get_session_context() as session:
            stmt = select(PlayHistory).where(PlayHistory.snapshot_id == snapshot_id)
            history = session.scalars(stmt).all()

            return [
                {
                    "persistent_id": ph.persistent_id,
                    "snapshot_id": ph.snapshot_id,
                    "played_count": ph.played_count,
                    "skipped_count": ph.skipped_count,
                    "played_date": ph.played_date,
                    "rating": ph.rating,
                }
                for ph in history
            ]

    def insert_play_history(self, history_data: Dict):
        """Insert a play history record"""
        with get_session_context() as session:
            play_history = PlayHistory(
                persistent_id=history_data["persistent_id"],
                snapshot_id=history_data["snapshot_id"],
                played_count=history_data.get("played_count", 0),
                skipped_count=history_data.get("skipped_count", 0),
                played_date=history_data.get("played_date"),
                rating=history_data.get("rating", 0),
            )
            session.add(play_history)

    def get_all_play_history(self) -> List[Dict]:
        """Get all play history records"""
        with get_session_context() as session:
            stmt = select(PlayHistory)
            history = session.scalars(stmt).all()

            return [
                {
                    "persistent_id": ph.persistent_id,
                    "snapshot_id": ph.snapshot_id,
                    "played_count": ph.played_count,
                    "skipped_count": ph.skipped_count,
                    "played_date": ph.played_date,
                    "rating": ph.rating,
                }
                for ph in history
            ]

    # DailyPlay Operations

    def upsert_daily_play(self, daily_data: Dict):
        """Insert or update a daily play record"""
        with get_session_context() as session:
            persistent_id = daily_data["persistent_id"]
            date_str = daily_data["date"]

            stmt = select(DailyPlay).where(
                DailyPlay.persistent_id == persistent_id, DailyPlay.date == date_str
            )
            existing = session.scalar(stmt)

            if existing:
                existing.plays_delta += daily_data.get("plays_delta", 0)
                existing.skips_delta += daily_data.get("skips_delta", 0)
            else:
                daily_play = DailyPlay(
                    persistent_id=persistent_id,
                    date=date_str,
                    plays_delta=daily_data.get("plays_delta", 0),
                    skips_delta=daily_data.get("skips_delta", 0),
                )
                session.add(daily_play)

    def get_daily_play(self, persistent_id: str, date: str) -> Optional[Dict]:
        """Get a daily play record"""
        with get_session_context() as session:
            stmt = select(DailyPlay).where(
                DailyPlay.persistent_id == persistent_id, DailyPlay.date == date
            )
            daily = session.scalar(stmt)

            if daily:
                return {
                    "persistent_id": daily.persistent_id,
                    "date": daily.date,
                    "plays_delta": daily.plays_delta,
                    "skips_delta": daily.skips_delta,
                }
            return None

    def get_all_daily_plays(self) -> List[Dict]:
        """Get all daily play records"""
        with get_session_context() as session:
            stmt = select(DailyPlay)
            dailies = session.scalars(stmt).all()

            return [
                {
                    "persistent_id": dp.persistent_id,
                    "date": dp.date,
                    "plays_delta": dp.plays_delta,
                    "skips_delta": dp.skips_delta,
                }
                for dp in dailies
            ]

    # Query Operations (Reporting)

    def query_top_tracks(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top tracks by play count"""
        with get_session_context() as session:
            stmt = (
                select(
                    Track.name,
                    Track.artist,
                    func.sum(DailyPlay.plays_delta).label("plays"),
                )
                .join(DailyPlay)
                .where(DailyPlay.date >= start_date, DailyPlay.date <= end_date)
                .group_by(Track.persistent_id)
                .order_by(func.sum(DailyPlay.plays_delta).desc())
                .limit(limit)
            )
            results = session.execute(stmt).all()

            return [
                {"name": name, "artist": artist, "plays": plays}
                for name, artist, plays in results
            ]

    def query_top_artists(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top artists by play count"""
        with get_session_context() as session:
            stmt = (
                select(Track.artist, func.sum(DailyPlay.plays_delta).label("plays"))
                .join(DailyPlay)
                .where(
                    DailyPlay.date >= start_date,
                    DailyPlay.date <= end_date,
                    Track.artist.isnot(None),
                )
                .group_by(Track.artist)
                .order_by(func.sum(DailyPlay.plays_delta).desc())
                .limit(limit)
            )
            results = session.execute(stmt).all()

            return [{"artist": artist, "plays": plays} for artist, plays in results]

    def query_top_albums(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top albums by play count"""
        with get_session_context() as session:
            stmt = (
                select(
                    Track.album,
                    Track.artist,
                    func.sum(DailyPlay.plays_delta).label("plays"),
                )
                .join(DailyPlay)
                .where(
                    DailyPlay.date >= start_date,
                    DailyPlay.date <= end_date,
                    Track.album.isnot(None),
                )
                .group_by(Track.album)
                .order_by(func.sum(DailyPlay.plays_delta).desc())
                .limit(limit)
            )
            results = session.execute(stmt).all()

            return [
                {"album": album, "artist": artist, "plays": plays}
                for album, artist, plays in results
            ]

    def query_top_genres(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query top genres by play count"""
        with get_session_context() as session:
            stmt = (
                select(Track.genre, func.sum(DailyPlay.plays_delta).label("plays"))
                .join(DailyPlay)
                .where(
                    DailyPlay.date >= start_date,
                    DailyPlay.date <= end_date,
                    Track.genre.isnot(None),
                )
                .group_by(Track.genre)
                .order_by(func.sum(DailyPlay.plays_delta).desc())
                .limit(limit)
            )
            results = session.execute(stmt).all()

            return [{"genre": genre, "plays": plays} for genre, plays in results]

    def query_most_skipped(
        self, start_date: str, end_date: str, limit: int
    ) -> List[Dict]:
        """Query most skipped tracks"""
        with get_session_context() as session:
            stmt = (
                select(
                    Track.name,
                    Track.artist,
                    func.sum(DailyPlay.skips_delta).label("skips"),
                )
                .join(DailyPlay)
                .where(
                    DailyPlay.date >= start_date,
                    DailyPlay.date <= end_date,
                    DailyPlay.skips_delta > 0,
                )
                .group_by(Track.persistent_id)
                .order_by(func.sum(DailyPlay.skips_delta).desc())
                .limit(limit)
            )
            results = session.execute(stmt).all()

            return [
                {"name": name, "artist": artist, "skips": skips}
                for name, artist, skips in results
            ]

    def query_listening_stats(self, start_date: str, end_date: str) -> Dict:
        """Query listening statistics"""
        with get_session_context() as session:
            stmt = (
                select(
                    func.sum(DailyPlay.plays_delta).label("total_plays"),
                    func.sum(DailyPlay.skips_delta).label("total_skips"),
                    func.count(func.distinct(DailyPlay.persistent_id)).label(
                        "unique_tracks"
                    ),
                    func.sum(DailyPlay.plays_delta * Track.duration).label(
                        "total_time"
                    ),
                )
                .join(Track)
                .where(DailyPlay.date >= start_date, DailyPlay.date <= end_date)
            )
            result = session.execute(stmt).one()

            return {
                "total_plays": result.total_plays or 0,
                "total_skips": result.total_skips or 0,
                "unique_tracks": result.unique_tracks or 0,
                "total_time": result.total_time or 0,
            }

    def query_stats(self) -> Dict:
        """Query overall database statistics"""
        with get_session_context() as session:
            total_tracks = session.scalar(select(func.count(Track.persistent_id)))
            total_snapshots = session.scalar(select(func.count(Snapshot.snapshot_id)))

            earliest_snapshot = session.scalar(
                select(Snapshot).order_by(Snapshot.timestamp).limit(1)
            )
            latest_snapshot = session.scalar(
                select(Snapshot).order_by(Snapshot.timestamp.desc()).limit(1)
            )

            earliest_date = session.scalar(select(func.min(DailyPlay.date)))
            latest_date = session.scalar(select(func.max(DailyPlay.date)))

            return {
                "total_tracks": total_tracks or 0,
                "total_snapshots": total_snapshots or 0,
                "earliest_date": earliest_date,
                "latest_date": latest_date,
                "earliest_snapshot": earliest_snapshot.timestamp.isoformat()
                if earliest_snapshot
                else None,
                "latest_snapshot": latest_snapshot.timestamp.isoformat()
                if latest_snapshot
                else None,
            }
