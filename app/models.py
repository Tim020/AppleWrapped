#!/usr/bin/env python3
"""
Apple Music History Tracker - SQLAlchemy Models
"""

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from contextlib import contextmanager
from datetime import datetime

Base = declarative_base()


class Track(Base):
    """Master list of all tracks with relatively static metadata"""

    __tablename__ = "tracks"

    persistent_id = Column(String(16), primary_key=True)
    name = Column(String(512), nullable=False)
    artist = Column(String(255))
    album = Column(String(255))
    album_artist = Column(String(255))
    genre = Column(String(100))
    year = Column(Integer)
    duration = Column(Float)  # Duration in seconds
    track_number = Column(Integer)
    disc_number = Column(Integer)
    date_added = Column(String(50))  # Store as ISO string from Apple
    location = Column(String(1024))
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)

    # Relationships
    play_history = relationship(
        "PlayHistory", back_populates="track", cascade="all, delete-orphan"
    )
    daily_plays = relationship(
        "DailyPlay", back_populates="track", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Track(persistent_id='{self.persistent_id}', name='{self.name}', artist='{self.artist}')>"


# Create indexes
Index("idx_tracks_artist", Track.artist)
Index("idx_tracks_album", Track.album)
Index("idx_tracks_genre", Track.genre)


class Snapshot(Base):
    """Records of when we collected data"""

    __tablename__ = "snapshots"

    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, unique=True, default=datetime.now)
    total_tracks = Column(Integer, nullable=False)
    collection_duration_seconds = Column(Float)
    notes = Column(String(512))

    # Relationships
    play_history = relationship(
        "PlayHistory", back_populates="snapshot", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Snapshot(id={self.snapshot_id}, timestamp='{self.timestamp}', tracks={self.total_tracks})>"


Index("idx_snapshots_timestamp", Snapshot.timestamp)


class PlayHistory(Base):
    """Time-series data of play counts"""

    __tablename__ = "play_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    persistent_id = Column(
        String(16), ForeignKey("tracks.persistent_id"), nullable=False
    )
    snapshot_id = Column(Integer, ForeignKey("snapshots.snapshot_id"), nullable=False)
    played_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    played_date = Column(String(50))  # Last played date from Apple Music
    rating = Column(Integer, default=0)

    # Relationships
    track = relationship("Track", back_populates="play_history")
    snapshot = relationship("Snapshot", back_populates="play_history")

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("persistent_id", "snapshot_id", name="uix_track_snapshot"),
    )

    def __repr__(self):
        return f"<PlayHistory(track='{self.persistent_id}', snapshot={self.snapshot_id}, plays={self.played_count})>"


Index("idx_play_history_persistent_id", PlayHistory.persistent_id)
Index("idx_play_history_snapshot_id", PlayHistory.snapshot_id)
Index("idx_play_history_played_count", PlayHistory.played_count)


class DailyPlay(Base):
    """Computed daily plays (derived data for performance)"""

    __tablename__ = "daily_plays"

    persistent_id = Column(
        String(16), ForeignKey("tracks.persistent_id"), primary_key=True
    )
    date = Column(String(10), primary_key=True)  # YYYY-MM-DD format
    plays_delta = Column(Integer, nullable=False)
    skips_delta = Column(Integer, nullable=False)

    # Relationships
    track = relationship("Track", back_populates="daily_plays")

    def __repr__(self):
        return f"<DailyPlay(track='{self.persistent_id}', date='{self.date}', plays={self.plays_delta})>"


Index("idx_daily_plays_date", DailyPlay.date)


# Module-level singletons for engine and session factory
_engine = None
_SessionFactory = None


def init_database(db_path):
    """Initialize database and create all tables (returns cached engine if already initialized)"""
    global _engine, _SessionFactory

    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{db_path}",
            # SQLite-specific optimizations
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,  # Verify connections before using
            echo=False,  # Control via logging instead
        )
        Base.metadata.create_all(_engine)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)

    return _engine


@contextmanager
def get_session_context():
    """Context manager for database sessions with automatic cleanup"""
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    session = _SessionFactory()
    try:
        yield session
        session.commit()  # Auto-commit on success
    except Exception:
        session.rollback()  # Auto-rollback on failure
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Get a new session (deprecated - use get_session_context instead)"""
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _SessionFactory()
