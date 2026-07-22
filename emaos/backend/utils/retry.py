"""
EMAOS — Retry Utility
Exponential backoff decorator for LLM calls and tool use.
"""
import asyncio
import functools
import logging
import random
import time
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


def retry_sync(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: float = 0.1,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """Synchronous exponential-backoff retry decorator."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exc: Optional[Exception] = None
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            f"[RETRY] {func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    jitter_offset = random.uniform(-jitter, jitter) * delay
                    sleep_time = delay + jitter_offset
                    logger.warning(
                        f"[RETRY] {func.__name__} attempt {attempt}/{max_attempts} failed: {exc}. "
                        f"Retrying in {sleep_time:.2f}s..."
                    )
                    if on_retry:
                        on_retry(attempt, exc, sleep_time)
                    time.sleep(max(0.01, sleep_time))
                    delay *= backoff_factor
            raise last_exc  # type: ignore
        return wrapper
    return decorator


def retry_async(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: float = 0.1,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """Asynchronous exponential-backoff retry decorator."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exc: Optional[Exception] = None
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            f"[RETRY] {func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    jitter_offset = random.uniform(-jitter, jitter) * delay
                    sleep_time = delay + jitter_offset
                    logger.warning(
                        f"[RETRY] {func.__name__} attempt {attempt}/{max_attempts} failed: {exc}. "
                        f"Retrying in {sleep_time:.2f}s..."
                    )
                    if on_retry:
                        on_retry(attempt, exc, sleep_time)
                    await asyncio.sleep(max(0.01, sleep_time))
                    delay *= backoff_factor
            raise last_exc  # type: ignore
        return wrapper
    return decorator
