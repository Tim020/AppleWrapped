#!/usr/bin/env python3
"""
Centralized logging configuration using structlog
"""

import sys
import logging
import structlog
from structlog.typing import FilteringBoundLogger


def configure_logging(verbosity: int = 0) -> FilteringBoundLogger:
    """
    Configure structlog with verbosity levels

    Args:
        verbosity: 0=WARNING, 1=INFO, 2=DEBUG

    Returns:
        Configured logger instance
    """
    # Map verbosity to log levels
    level_map = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG
    }
    log_level = level_map.get(verbosity, logging.WARNING)

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Build processor chain
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    # Add callsite info only at DEBUG level
    if log_level == logging.DEBUG:
        processors.append(
            structlog.processors.CallsiteParameterAdder({
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            })
        )

    # Use colored console renderer for TTY, JSON for pipes
    if sys.stdout.isatty():
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        )
    else:
        processors.append(structlog.processors.JSONRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger()


# Default logger instance (will be reconfigured by main)
logger = structlog.get_logger()
