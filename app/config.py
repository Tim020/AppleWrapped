#!/usr/bin/env python3
"""
Configuration management for database backends
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class CouchbaseConfig:
    """Configuration for Couchbase connection"""

    host: Optional[str] = None
    port: int = 8091
    username: str = ""
    password: str = ""
    bucket_name: str = "apple_wrapped"
    scope_name: str = "_default"

    # Collection names
    tracks_collection: str = "tracks"
    snapshots_collection: str = "snapshots"
    playhistory_collection: str = "playhistory"
    dailyplays_collection: str = "dailyplays"
    counters_collection: str = "counters"

    @classmethod
    def from_args_and_env(cls, args) -> "CouchbaseConfig":
        """
        Create config from CLI arguments and environment variables
        Priority: CLI args > Environment variables > Defaults

        Args:
            args: Parsed command line arguments

        Returns:
            CouchbaseConfig instance
        """
        # Get host from CLI or environment
        host = getattr(args, "couchbase_host", None) or os.getenv("COUCHBASE_HOST")

        # Get port from CLI or environment
        port = getattr(args, "couchbase_port", None) or os.getenv("COUCHBASE_PORT")
        if port:
            port = int(port)
        else:
            port = 8091

        # Get username from CLI or environment
        username = getattr(args, "couchbase_username", None) or os.getenv(
            "COUCHBASE_USERNAME", ""
        )

        # Get password from CLI or environment
        password = getattr(args, "couchbase_password", None) or os.getenv(
            "COUCHBASE_PASSWORD", ""
        )

        return cls(host=host, port=port, username=username, password=password)

    def is_configured(self) -> bool:
        """
        Check if Couchbase is configured (has at minimum a host)

        Returns:
            bool: True if host is configured
        """
        return self.host is not None and self.host != ""

    def get_connection_string(self) -> str:
        """
        Get Couchbase connection string

        Returns:
            str: Connection string in format couchbase://host
        """
        if not self.is_configured():
            raise ValueError("Couchbase host not configured")
        return f"couchbase://{self.host}"
