from __future__ import annotations

from pathlib import Path
from typing import Any


def build_checkpointer(checkpoint_path: str | None = None) -> Any:
    """Create a LangGraph checkpointer.

    SQLite gives the demo cross-process resume support. If the optional SQLite
    package is not installed, fall back to in-memory checkpoints for tests.
    """

    if checkpoint_path:
        import sqlite3

        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError:
            return build_memory_checkpointer()

        path = Path(checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), check_same_thread=False)
        saver = SqliteSaver(connection)
        if hasattr(saver, "setup"):
            saver.setup()
        return saver

    return build_memory_checkpointer()


def build_memory_checkpointer() -> Any:
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()
