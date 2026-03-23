"""CLI loading spinner with superhero phrases.

Renders a braille-dot spinner on a single line with ``\\r`` overwriting.
Thread-safe start/stop/swap driven by ``threading.Event``.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import IO, Any

_BRAILLE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_BANNER = r"""
 ____                          _                    _
/ ___| _   _ _ __   ___ _ __  / \   __ _  ___ _ __ | |_ ___
\___ \| | | | '_ \ / _ \ '__// _ \ / _` |/ _ \ '_ \| __/ __|
 ___) | |_| | |_) |  __/ | / ___ \ (_| |  __/ | | | |_\__ \
|____/ \__,_| .__/ \___|_|/_/   \_\__, |\___|_| |_|\__|___/
            |_|                   |___/
""".lstrip("\n")

PHRASES = [
    # Action & Combat
    "Smashing the mainframe...",
    "Busting the bad guys...",
    "Dodging lasers...",
    "Deflecting incoming bugs...",
    "Wrangling the villains...",
    "Blasting through the data...",
    "Shielding the core...",
    # Movement & Patrol
    "Soaring through the cloud(s)...",
    "Leaping tall buildings...",
    "Swinging across the city...",
    "Teleporting to the server...",
    "Sprinting at superhuman speeds...",
    "Patrolling the sector...",
    "Gliding into position...",
    # Tech & Preparation
    "Assembling the team...",
    "Calibrating the utility belt...",
    "Charging the repulsors...",
    "Scanning for evil-doers...",
    "Activating X-ray vision...",
    "Donning the cape...",
    "Polishing the armor...",
    "Analyzing kryptonite levels...",
    # Pure Heroics
    "Saving the universe...",
    "Upholding justice...",
    "Rescuing the citizens...",
    "Averting disaster...",
    "Restoring peace to the galaxy...",
    "Defending the innocent...",
]


def _is_tty() -> bool:
    """Check if stdout is a TTY.

    Returns:
        True if stdout is connected to a terminal.
    """
    return sys.stdout.isatty()


def print_banner(version: str, *, file: IO[Any] | None = None) -> None:
    """Print the SuperAgents ASCII banner with version and tagline.

    Args:
        version: Package version string.
        file: Output stream (defaults to stdout).
    """
    out = file or sys.stdout
    if _is_tty():
        # Cyan banner
        print(f"\033[36m{_BANNER}\033[0m", file=out, flush=True)  # noqa: T201
    else:
        print(_BANNER, file=out, flush=True)  # noqa: T201
    print(  # noqa: T201
        f"  v{version} | Not all coding heroes wear capes...",
        file=out, flush=True,
    )
    print(  # noqa: T201
        "  " + "\u2500" * 55,
        file=out, flush=True,
    )
    print(file=out, flush=True)  # noqa: T201


class Spinner:
    """Braille-dot spinner that runs on a background thread.

    The spinner renders a cycling braille character and a phrase on a single
    line, overwriting with ``\\r``. Call ``start()`` to begin, ``stop()`` to
    end, and ``swap()`` to change the phrase mid-spin.

    Args:
        file: Output stream (defaults to stdout). Useful for testing.
        force_tty: Override TTY detection. When False the spinner is disabled.
            When None (default), uses ``_is_tty()`` to decide.
    """

    def __init__(
        self,
        *,
        file: IO[Any] | None = None,
        force_tty: bool | None = None,
    ) -> None:
        self._file = file or sys.stdout
        self._enabled = force_tty if force_tty is not None else _is_tty()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._phrase = ""
        self._lock = threading.Lock()

    def start(self, phrase: str) -> None:
        """Start the spinner with a phrase.

        If already running, swaps the phrase instead.

        Args:
            phrase: Text to display next to the spinner.
        """
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            self.swap(phrase)
            return
        self._phrase = phrase
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the spinner and clear the line."""
        if self._thread is None or not self._thread.is_alive():
            return
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        self._thread = None
        # Clear the spinner line
        self._file.write("\r" + " " * 60 + "\r")
        self._file.flush()

    def swap(self, phrase: str) -> None:
        """Change the displayed phrase without stopping the spinner.

        Args:
            phrase: New phrase to display.
        """
        with self._lock:
            self._phrase = phrase

    def is_alive(self) -> bool:
        """Check if the spinner thread is running.

        Returns:
            True if the background thread is active.
        """
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        """Spinner loop — runs on background thread."""
        idx = 0
        while not self._stop_event.is_set():
            frame = _BRAILLE_FRAMES[idx % len(_BRAILLE_FRAMES)]
            with self._lock:
                phrase = self._phrase
            self._file.write(f"\r  {frame} {phrase}")
            self._file.flush()
            idx += 1
            time.sleep(0.1)
