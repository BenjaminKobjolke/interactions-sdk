"""Low-level JSON protocol for communicating with the interactive scheduler.

Streams default to ``sys.stdin`` / ``sys.stdout`` but can be overridden
per-thread via :func:`set_streams` so the protocol works inside bot
adapters and other in-process hosts.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from typing import Any


class InteractionError(Exception):
    """Raised when the scheduler returns an error response."""

    def __init__(self, message: str, prompt_id: str) -> None:
        super().__init__(message)
        self.prompt_id = prompt_id


# ---------------------------------------------------------------------------
# Thread-local stream overrides
# ---------------------------------------------------------------------------

_local = threading.local()


def set_streams(
    input_stream: Any = None, output_stream: Any = None,
) -> None:
    """Set per-thread I/O streams for the JSON protocol.

    Pass ``None`` to revert to ``sys.stdin`` / ``sys.stdout``.
    """
    _local.input_stream = input_stream
    _local.output_stream = output_stream


def has_custom_streams() -> bool:
    """Return True if custom streams are set on the current thread."""
    return getattr(_local, "input_stream", None) is not None


def _get_input() -> Any:
    """Return the active input stream (custom or sys.stdin)."""
    return getattr(_local, "input_stream", None) or sys.stdin


def _get_output() -> Any:
    """Return the active output stream (custom or sys.stdout)."""
    return getattr(_local, "output_stream", None) or sys.stdout


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def _generate_id() -> str:
    """Generate a unique prompt ID."""
    return str(uuid.uuid4())


def _send_prompt(
    prompt_type: str,
    message: str,
    *,
    prompt_id: str | None = None,
    default: Any = None,
    options: list[str] | None = None,
    hidden_options: dict[str, str] | None = None,
) -> Any:
    """Send a prompt via the output stream and read the response from the input stream.

    Args:
        prompt_type: One of "confirm", "input", "choice"
        message: The question text
        prompt_id: Optional custom ID (auto-generated if not provided)
        default: Default value used on timeout
        options: List of options (for choice prompts)
        hidden_options: Shortcut keys mapped to labels, accepted but not displayed

    Returns:
        The value from the response

    Raises:
        InteractionError: If the response contains an error field
    """
    if prompt_id is None:
        prompt_id = _generate_id()

    payload: dict[str, Any] = {
        "_interactive": True,
        "type": prompt_type,
        "id": prompt_id,
        "message": message,
    }
    if default is not None:
        payload["default"] = default
    if options is not None:
        payload["options"] = options
    if hidden_options is not None:
        payload["hidden_options"] = hidden_options

    out = _get_output()
    out.write(json.dumps(payload) + "\n")
    out.flush()

    response_line = _get_input().readline()
    response = json.loads(response_line)

    if "error" in response and response["error"]:
        raise InteractionError(response["error"], prompt_id)

    return response["value"]


def _send_output(text: str) -> None:
    """Send display-only text (fire-and-forget, no response expected).

    Args:
        text: The text to display to the user.
    """
    payload = {
        "_interactive": True,
        "type": "output",
        "id": "",
        "message": text,
    }
    out = _get_output()
    out.write(json.dumps(payload) + "\n")
    out.flush()
