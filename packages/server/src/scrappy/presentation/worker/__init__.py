"""Worker process: claim jobs, dispatch them, sleep when idle."""

from scrappy.presentation.worker.loop import (
    DispatchCallback,
    run_until_idle,
    run_worker,
    wait_for_run,
)

__all__ = ["DispatchCallback", "run_until_idle", "run_worker", "wait_for_run"]
