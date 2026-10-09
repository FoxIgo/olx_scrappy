"""Structured logging (structlog) configured once per process, level from settings."""

from __future__ import annotations

import logging
import sys

import structlog

_NOISY = ("httpx", "httpcore", "openai", "aiosqlite", "asyncio", "curl_cffi")


class _StderrHandler(logging.StreamHandler):  # pyright: ignore[reportMissingTypeArgument]
    """Writes to whatever ``sys.stderr`` is at emit time (survives stream swapping)."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self) -> object:  # pyright: ignore[reportIncompatibleVariableOverride]
        return sys.stderr

    @stream.setter
    def stream(self, value: object) -> None:
        pass


def configure_logging(level: str = "INFO") -> None:
    """Route structlog and stdlib logging (the adapters use stdlib) to stderr, rendered by
    structlog. Idempotent: calling again only changes the level."""
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = _StderrHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            ],
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, _StderrHandler)]:
        root.removeHandler(old)  # keep foreign handlers (e.g. pytest's)
    root.addHandler(handler)
    root.setLevel(level)
    numeric = logging.getLevelNamesMapping()[level]
    for name in _NOISY:
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
