"""Interactions SDK — interactive prompts for scheduled scripts.

Works in two modes automatically:
- **Interactive mode** (``INTERACTIVE=1``): JSON protocol over stdin/stdout
  for the task scheduler.
- **CLI mode** (no env var): Falls back to console ``input()`` prompts so
  scripts work stand-alone without any wrapper code.

Usage:
    from interactions_sdk import confirm, ask, choose, output

    if confirm("Deploy to production?", default=True):
        env = choose("Select environment:", ["staging", "production"], default=0)
        version = ask("Enter version:", default="1.0.0")
        output(f"Deploying version {version} to environment {env}")
"""

from __future__ import annotations

import os

from ._protocol import InteractionError, _send_output, _send_prompt, set_streams

__all__ = [
    "AbortError",
    "ENV_MARKER",
    "InteractionChoice",
    "InteractionError",
    "ask",
    "ask_or_accept",
    "choose",
    "confirm",
    "is_interactive",
    "output",
    "set_streams",
    "start_output_capture",
    "stop_output_capture",
]

ENV_MARKER = "INTERACTIVE"


class AbortError(Exception):
    """Raised when the user does not answer an interactive prompt."""


# ---------------------------------------------------------------------------
# Output capture
# ---------------------------------------------------------------------------

_capture_buffer: list[str] | None = None
_capture_silent: bool = False


def start_output_capture(*, silent: bool = False) -> None:
    """Begin capturing output() calls into a buffer.

    When *silent* is True, captured text is **not** printed to the user.
    """
    global _capture_buffer, _capture_silent
    _capture_buffer = []
    _capture_silent = silent


def stop_output_capture() -> str:
    """Stop capturing and return all captured text joined by newlines."""
    global _capture_buffer, _capture_silent
    result = "\n".join(_capture_buffer) if _capture_buffer else ""
    _capture_buffer = None
    _capture_silent = False
    return result


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def is_interactive() -> bool:
    """Check if running in interactive mode (scheduler or custom streams)."""
    from ._protocol import has_custom_streams
    return has_custom_streams() or os.getenv(ENV_MARKER) == "1"


def output(text: str) -> None:
    """Display text to the user.

    When running under the task scheduler, sends through the protocol.
    Otherwise, prints directly to stdout with unicode safety.
    """
    if _capture_buffer is not None:
        _capture_buffer.append(text)
        if _capture_silent:
            return
    if is_interactive():
        if text:
            _send_output(text)
    else:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))


def confirm(
    message: str, *, default: bool | None = None, id: str | None = None
) -> bool:
    """Ask user for yes/no confirmation.

    In interactive mode delegates to the scheduler protocol.
    In CLI mode falls back to console ``input()``.
    """
    if is_interactive():
        result = _send_prompt("confirm", message, prompt_id=id, default=default)
        if result is None:
            raise AbortError("User did not answer confirm prompt")
        return bool(result)
    # CLI fallback
    if default is None:
        hint = "y/n"
    else:
        hint = "Y/n" if default else "y/N"
    raw = input(f"{message} [{hint}]: ").strip().lower()
    if not raw:
        if default is None:
            return False
        return default
    return raw in ("y", "yes")


def ask(
    message: str, *, default: str | None = None, id: str | None = None
) -> str:
    """Ask user for text input.

    In interactive mode delegates to the scheduler protocol.
    In CLI mode falls back to console ``input()``.
    """
    if is_interactive():
        result = _send_prompt("input", message, prompt_id=id, default=default)
        if result is None:
            raise AbortError("User did not answer ask prompt")
        return str(result)
    # CLI fallback
    prompt = f"{message} [{default}]: " if default else f"{message}: "
    raw = input(prompt).strip()
    return raw if raw else (default or "")


def choose(
    message: str,
    options: list[str],
    *,
    default: int | None = None,
    id: str | None = None,
    hidden_options: dict[str, str] | None = None,
) -> int:
    """Ask user to pick from a list of options.

    In interactive mode delegates to the scheduler protocol.
    In CLI mode falls back to a numbered menu with console ``input()``.
    """
    if is_interactive():
        result = _send_prompt(
            "choice", message, prompt_id=id, default=default,
            options=options, hidden_options=hidden_options,
        )
        if result is None:
            raise AbortError("User did not answer choose prompt")
        return int(result)
    # CLI fallback — numbered menu
    print(message)
    for i, opt in enumerate(options):
        marker = " *" if i == default else ""
        print(f"  [{i}] {opt}{marker}")
    hidden_keys: list[str] = []
    if hidden_options:
        hidden_keys = list(hidden_options.keys())
        hints = ", ".join(f"{k}={label}" for k, label in hidden_options.items())
        print(f"  ({hints})")
    while True:
        prompt = f"Choice [{default}]: " if default is not None else "Choice: "
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if raw in hidden_keys:
            return len(options) + hidden_keys.index(raw)
        try:
            val = int(raw)
            if 0 <= val < len(options):
                return val
        except ValueError:
            pass
        print(f"  Please enter 0-{len(options) - 1}")


# ---------------------------------------------------------------------------
# Higher-level helpers
# ---------------------------------------------------------------------------

def ask_or_accept(label: str, *, default: str) -> str:
    """Show accept/edit choice, only prompt for text if user picks edit."""
    action = choose(f"{label} {default}", ["Accept", "Edit"], default=0)
    if action == 1:
        return ask(label, default=default)
    return default


class InteractionChoice:
    """Maps display labels to action keys for choose()."""

    _ABORT_KEY = "a"
    _ABORT_LABEL = "Abort"
    _ABORT_ACTION = "abort"

    def __init__(
        self,
        prompt: str,
        choices: list[tuple[str, str]],
        *,
        default: int = 0,
        abort: bool = False,
    ) -> None:
        self._prompt = prompt
        self._choices = choices
        self._default = default
        self._abort = abort

    def choose(self) -> str:
        """Show the menu and return the selected action key."""
        labels = [label for label, _ in self._choices]
        hidden = {self._ABORT_KEY: self._ABORT_LABEL} if self._abort else None
        index = choose(self._prompt, labels, default=self._default, hidden_options=hidden)
        if index < len(self._choices):
            return self._choices[index][1]
        return self._ABORT_ACTION
