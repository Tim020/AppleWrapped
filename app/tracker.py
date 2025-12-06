"""
Apple Music History Tracker
Collects periodic snapshots of your Apple Music library using SQLAlchemy ORM
"""

import subprocess
import re
import time
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from app.logging_config import logger


def get_track_count():
    """Get total number of tracks in library"""
    cmd = [
        "osascript",
        "-e",
        'tell application "Music" to get count of tracks of library playlist 1',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return int(result.stdout.strip())


def get_track_properties(index):
    """Get properties of a specific track by index (1-based)"""
    cmd = [
        "osascript",
        "-e",
        f'tell application "Music" to get properties of track {index} of library playlist 1',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return None

    return parse_properties(result.stdout.strip())


def parse_properties(props_str):
    """Parse the properties string returned by AppleScript"""
    props = {}

    # Persistent ID (most important!)
    match = re.search(r"persistent ID:([A-F0-9]+)", props_str)
    if match:
        props["persistent_id"] = match.group(1).strip()
    else:
        return None  # Can't track without persistent ID

    # Name
    match = re.search(r"name:(.*?)(?:, persistent ID:|$)", props_str)
    if match:
        props["name"] = match.group(1).strip()

    # Artist
    match = re.search(r"artist:(.*?)(?:, album artist:|$)", props_str)
    if match:
        props["artist"] = match.group(1).strip()

    # Album
    match = re.search(r"album:(.*?)(?:, genre:|$)", props_str)
    if match:
        props["album"] = match.group(1).strip()

    # Album artist
    match = re.search(r"album artist:(.*?)(?:, composer:|$)", props_str)
    if match:
        props["album_artist"] = match.group(1).strip()

    # Genre
    match = re.search(r"genre:(.*?)(?:, bit rate:|$)", props_str)
    if match:
        props["genre"] = match.group(1).strip()

    # Year
    match = re.search(r"year:(\d+)", props_str)
    if match:
        year = int(match.group(1))
        props["year"] = year if year != 0 else None

    # Duration (in seconds)
    match = re.search(r"duration:([\d.]+)", props_str)
    if match:
        props["duration"] = float(match.group(1))

    # Track number
    match = re.search(r"track number:(\d+)", props_str)
    if match:
        props["track_number"] = int(match.group(1))

    # Disc number
    match = re.search(r"disc number:(\d+)", props_str)
    if match:
        props["disc_number"] = int(match.group(1))

    # Played count
    match = re.search(r"played count:(\d+)", props_str)
    if match:
        props["played_count"] = int(match.group(1))

    # Skipped count
    match = re.search(r"skipped count:(\d+)", props_str)
    if match:
        props["skipped_count"] = int(match.group(1))

    # Date added
    match = re.search(r"date added:date (.*?)(?:, time:|$)", props_str)
    if match:
        props["date_added"] = match.group(1).strip()

    # Played date
    match = re.search(r"played date:date (.*?)(?:,|$)", props_str)
    if match:
        date_str = match.group(1).strip()
        if date_str != "missing value":
            props["played_date"] = date_str

    # Rating
    match = re.search(r"rating:(\d+)", props_str)
    if match:
        props["rating"] = int(match.group(1))

    # Location
    match = re.search(r"location:alias (.*?)$", props_str)
    if match:
        props["location"] = match.group(1).strip()

    return props


def collect_library_snapshot(max_workers=20):
    """Collect a complete snapshot of the library"""
    total_tracks = get_track_count()
    logger.info(f"Library scan started: {total_tracks} tracks")
    logger.info(f"Parallel collection started with {max_workers} workers")

    tracks = []
    progress_lock = Lock()
    completed = [0]
    start_time = time.time()

    def update_progress():
        with progress_lock:
            completed[0] += 1
            if completed[0] % 100 == 0 or completed[0] == total_tracks:
                elapsed = time.time() - start_time
                rate = completed[0] / elapsed if elapsed > 0 else 0
                eta = (total_tracks - completed[0]) / rate if rate > 0 else 0
                percent = round(completed[0] / total_tracks * 100, 1)
                logger.info(
                    f"Collection progress: {completed[0]}/{total_tracks} ({percent}%), ETA {round(eta)}s"
                )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(get_track_properties, i): i
            for i in range(1, total_tracks + 1)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                props = future.result()
                if props and "persistent_id" in props:
                    tracks.append(props)
            except Exception as e:
                logger.warning(f"Track collection failed for index {index}: {str(e)}")

            update_progress()

    collection_duration = time.time() - start_time
    logger.info(
        f"Collection complete: {len(tracks)} tracks collected in {round(collection_duration, 1)}s"
    )

    return tracks, collection_duration


def store_snapshot(backend_manager, tracks, collection_duration):
    """Store a snapshot in the database and calculate deltas using backend abstraction"""
    timestamp = datetime.now()
    timestamp_iso = timestamp.isoformat()
    snapshot_date = date.today().isoformat()

    # Create snapshot record
    snapshot_data = {
        "timestamp": timestamp_iso,
        "total_tracks": len(tracks),
        "collection_duration_seconds": collection_duration,
    }
    snapshot_id = backend_manager.create_snapshot(snapshot_data)

    logger.info(f"Snapshot storage started: ID {snapshot_id}, {len(tracks)} tracks")

    # Get previous snapshot for delta calculation
    prev_snapshot = backend_manager.get_previous_snapshot(timestamp_iso)

    # Get previous play counts for delta calculation
    prev_play_counts = {}
    if prev_snapshot:
        prev_history = backend_manager.get_play_history_for_snapshot(
            prev_snapshot["snapshot_id"]
        )

        for ph in prev_history:
            prev_play_counts[ph["persistent_id"]] = {
                "played": ph["played_count"],
                "skipped": ph["skipped_count"],
            }

    # Process tracks
    new_tracks = 0
    updated_tracks = 0
    daily_deltas = []

    for track_data in tracks:
        persistent_id = track_data["persistent_id"]

        # Check if track exists
        existing_track = backend_manager.get_track(persistent_id)

        # Prepare track dict for upsert
        track_dict = {
            "persistent_id": persistent_id,
            "name": track_data.get("name"),
            "artist": track_data.get("artist"),
            "album": track_data.get("album"),
            "album_artist": track_data.get("album_artist"),
            "genre": track_data.get("genre"),
            "year": track_data.get("year"),
            "duration": track_data.get("duration"),
            "track_number": track_data.get("track_number"),
            "disc_number": track_data.get("disc_number"),
            "date_added": track_data.get("date_added"),
            "location": track_data.get("location"),
            "last_seen": timestamp_iso,
        }

        if existing_track:
            # Track exists, will be updated
            updated_tracks += 1
        else:
            # New track
            track_dict["first_seen"] = timestamp_iso
            new_tracks += 1

        # Upsert track
        backend_manager.upsert_track(track_dict)

        # Create play history record
        history_dict = {
            "persistent_id": persistent_id,
            "snapshot_id": snapshot_id,
            "played_count": track_data.get("played_count", 0),
            "skipped_count": track_data.get("skipped_count", 0),
            "played_date": track_data.get("played_date"),
            "rating": track_data.get("rating", 0),
        }
        backend_manager.insert_play_history(history_dict)

        # Calculate deltas
        if prev_snapshot and persistent_id in prev_play_counts:
            prev = prev_play_counts[persistent_id]
            plays_delta = track_data.get("played_count", 0) - prev["played"]
            skips_delta = track_data.get("skipped_count", 0) - prev["skipped"]

            if plays_delta > 0 or skips_delta > 0:
                daily_deltas.append(
                    {
                        "persistent_id": persistent_id,
                        "date": snapshot_date,
                        "plays_delta": plays_delta,
                        "skips_delta": skips_delta,
                    }
                )
        elif not prev_snapshot and track_data.get("played_count", 0) > 0:
            # First snapshot: record all existing plays
            daily_deltas.append(
                {
                    "persistent_id": persistent_id,
                    "date": snapshot_date,
                    "plays_delta": track_data.get("played_count", 0),
                    "skips_delta": track_data.get("skipped_count", 0),
                }
            )

    # Insert daily deltas
    if daily_deltas:
        for delta in daily_deltas:
            backend_manager.upsert_daily_play(delta)

        logger.info(f"Recorded {len(daily_deltas)} daily play deltas")

    logger.info(
        f"Snapshot storage complete: ID {snapshot_id}, {new_tracks} new tracks, {updated_tracks} updated tracks"
    )

    return snapshot_id


def generate_wrapped_report(backend_manager, start_date=None, end_date=None, limit=10):
    """Generate a wrapped report for a date range using backend abstraction"""

    # Default to all time if no dates specified
    if start_date is None:
        stats = backend_manager.query_stats()
        start_date = stats.get("earliest_date") or date.today().isoformat()

    if end_date is None:
        end_date = date.today().isoformat()

    logger.info(f"Wrapped report started: {start_date} to {end_date}, top {limit}")

    print(f"\n{'=' * 70}")
    print(f"🎵  APPLE MUSIC WRAPPED: {start_date} to {end_date}")
    print(f"{'=' * 70}")

    # Total plays and listening time
    listening_stats = backend_manager.query_listening_stats(start_date, end_date)

    total_plays = listening_stats.get("total_plays", 0)
    total_skips = listening_stats.get("total_skips", 0)
    total_seconds = listening_stats.get("total_time", 0)

    total_hours = int(total_seconds // 3600)
    total_minutes = int((total_seconds % 3600) // 60)

    print("\n📊 LISTENING OVERVIEW")
    print(f"   Total plays: {total_plays:,}")
    print(f"   Total skips: {total_skips:,}")
    print(f"   Total listening time: {total_hours}h {total_minutes}m")

    # Top songs by play count
    top_songs = backend_manager.query_top_tracks(start_date, end_date, limit)

    if top_songs:
        print(f"\n🎤 TOP {len(top_songs)} SONGS")
        for i, song in enumerate(top_songs, 1):
            print(f"   {i:2d}. {song['name']} - {song['artist']}")
            print(f"       ({song['plays']} plays)")

    # Top artists by total plays
    top_artists = backend_manager.query_top_artists(start_date, end_date, limit)

    if top_artists:
        print(f"\n🎸 TOP {len(top_artists)} ARTISTS")
        for i, artist in enumerate(top_artists, 1):
            print(f"   {i:2d}. {artist['artist']} ({artist['plays']} plays)")

    # Top albums
    top_albums = backend_manager.query_top_albums(start_date, end_date, limit)

    if top_albums:
        print(f"\n💿 TOP {len(top_albums)} ALBUMS")
        for i, album in enumerate(top_albums, 1):
            print(
                f"   {i:2d}. {album['album']} - {album['artist']} ({album['plays']} plays)"
            )

    # Genre breakdown
    top_genres = backend_manager.query_top_genres(start_date, end_date, 5)

    if top_genres:
        print("\n🎼 TOP GENRES")
        for i, genre in enumerate(top_genres, 1):
            print(f"   {i}. {genre['genre']} ({genre['plays']} plays)")

    # Most skipped songs
    most_skipped = backend_manager.query_most_skipped(start_date, end_date, 5)

    if most_skipped:
        print("\n⏭️  MOST SKIPPED SONGS")
        for i, song in enumerate(most_skipped, 1):
            print(f"   {i}. {song['name']} - {song['artist']}")
            print(f"      ({song['skips']} skips)")

    # New discoveries (approximate from all tracks)
    # TODO: Add dedicated backend method for this query if needed
    all_tracks = backend_manager.get_all_tracks()
    year = start_date[:4]
    new_tracks_count = sum(
        1 for t in all_tracks if t.get("date_added") and year in t.get("date_added", "")
    )

    print("\n📅 NEW DISCOVERIES")
    print(f"   Tracks added: {new_tracks_count}")

    print(f"\n{'=' * 70}")

    logger.info(f"Wrapped report completed: {start_date} to {end_date}")


def collect_command(backend_manager, args):
    """Command to collect a new snapshot"""
    tracks, duration = collect_library_snapshot(max_workers=args.workers)

    snapshot_id = store_snapshot(backend_manager, tracks, duration)
    logger.info(f"Collect command complete: snapshot ID {snapshot_id}")


def report_command(backend_manager, args):
    """Command to generate a wrapped report"""
    generate_wrapped_report(backend_manager, args.start_date, args.end_date, args.limit)


def stats_command(backend_manager, args):
    """Command to show database statistics"""
    stats = backend_manager.query_stats()

    total_tracks = stats.get("total_tracks", 0)
    total_snapshots = stats.get("total_snapshots", 0)
    earliest_snapshot = stats.get("earliest_snapshot")
    latest_snapshot = stats.get("latest_snapshot")
    earliest_date = stats.get("earliest_date")
    latest_date = stats.get("latest_date")

    print(f"\n{'=' * 70}")
    print("📊 DATABASE STATISTICS")
    print(f"{'=' * 70}")
    print(f"Total unique tracks: {total_tracks:,}")
    print(f"Total snapshots: {total_snapshots:,}")

    if earliest_snapshot and latest_snapshot:
        print(f"First snapshot: {earliest_snapshot}")
        print(f"Latest snapshot: {latest_snapshot}")

        if earliest_date and latest_date:
            print(f"Play data available: {earliest_date} to {latest_date}")

    print(f"{'=' * 70}\n")
