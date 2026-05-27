from __future__ import annotations

import logging
import os
from typing import Optional


def configure_logging(*, level: Optional[str] = None) -> None:
    """
    Configure app-wide logging.

    Uses env var `LOG_LEVEL` by default.
    """
    resolved_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    # Avoid duplicate handlers when called multiple times (FastAPI startup).
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(numeric_level)
        return

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def get_logger(name: str = "claimorchestrator") -> logging.Logger:
    return logging.getLogger(name)

