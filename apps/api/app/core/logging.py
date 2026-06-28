import sys
from contextvars import ContextVar

from loguru import logger

from app.core.config import get_settings

# Set per-request by the request-id middleware (main.py); surfaced in every log
# line so logs from one request can be correlated.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def _patch_request_id(record) -> None:
    record["extra"].setdefault("request_id", request_id_var.get())


def configure_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.configure(patcher=_patch_request_id)

    if settings.log_json:
        # Structured: one JSON object per line (extra fields included).
        logger.add(sys.stdout, level=settings.log_level, serialize=True)
    else:
        logger.add(
            sys.stdout,
            level=settings.log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level:<7}</level> | "
                "<magenta>{extra[request_id]}</magenta> | "
                "<cyan>{name}:{line}</cyan> | {message}"
            ),
            colorize=True,
        )
