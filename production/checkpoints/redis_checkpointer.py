from __future__ import annotations

from typing import Any, Optional


def get_checkpointer(
    *,
    redis_url: Optional[str] = None,
    namespace: str = "claimorchestrator",
) -> Any:
    """
    Return a LangGraph checkpointer.

    - If `redis_url` is provided, attempt to use a Redis-backed saver.
    - Otherwise, fall back to an in-memory saver.

    Note: LangGraph's Redis checkpointer API can vary by version. This function
    intentionally uses defensive imports to keep the project bootstrappable.
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "LangGraph is not installed. Install `langgraph` to use checkpoints."
        ) from e

    if not redis_url:
        return MemorySaver()

    try:
        from langgraph.checkpoint.redis import RedisSaver  # type: ignore
    except Exception:
        # Redis saver not available in this LangGraph version.
        return MemorySaver()

    # Try common constructor/factory patterns.
    try:
        if hasattr(RedisSaver, "from_conn_info"):
            return RedisSaver.from_conn_info(redis_url=redis_url, namespace=namespace)  # type: ignore[attr-defined]
    except Exception:
        pass

    for args, kwargs in [
        ((), {"redis_url": redis_url, "namespace": namespace}),
        ((), {"url": redis_url, "namespace": namespace}),
        ((), {"redis_url": redis_url, "key_prefix": namespace}),
        ((), {"url": redis_url, "key_prefix": namespace}),
        ((redis_url,), {"namespace": namespace}),
    ]:
        try:
            return RedisSaver(*args, **kwargs)  # type: ignore[misc]
        except Exception:
            continue

    # Final fallback.
    return MemorySaver()

