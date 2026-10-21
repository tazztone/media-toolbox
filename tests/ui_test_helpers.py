"""Shared test helpers and lazy fixtures for Libadwaita / UI test suites.

Zero top-level `import gi` to prevent polluting sys.modules before AST scanner runs.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

import inspect
import sys
from typing import Any, Callable
import pytest

from media_toolbox.core.models import (
    AudioStream,
    FormatInfo,
    MediaInfo,
    VideoStream,
)


def get_gi_modules():
    """Lazily load PyGObject modules without polluting module collection namespace."""
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

    return gi, Gtk, Gdk, Adw, Gio, GLib


@pytest.fixture
def gi_env():
    """Fixture supplying PyGObject modules."""
    return get_gi_modules()


def _raw_iteration(ctx: Any) -> Callable[..., bool]:
    """Return GLib's C-level MainContext.iteration, skipping PyGObject's wrapper.

    The wrapper pauses gi.events' asyncio loop; these tests never create an
    asyncio loop, so it is a no-op — but importing gi.events emits Python 3.14
    asyncio deprecation warnings. Walk the MRO and pick the first non-Python
    implementation so this survives PyGObject dropping/keeping the override.
    """
    for klass in type(ctx).__mro__[1:]:
        candidate = klass.__dict__.get("iteration")
        if candidate is not None and not inspect.isfunction(candidate):
            return candidate
    return type(ctx).iteration


def iterate_main_context(ctx: Any) -> bool:
    return _raw_iteration(ctx)(ctx, False)


def drain_main_context(ctx: Any, limit: int = 1000) -> None:
    raw = _raw_iteration(ctx)
    for _ in range(limit):
        if not ctx.pending():
            return
        raw(ctx, False)
    raise AssertionError(f"GLib main context still pending after {limit} iterations")


@pytest.fixture(autouse=True, scope="module")
def isolate_gi_sys_modules():
    """Module-level teardown fixture ensuring UI modules do not leak

    into sys.modules after UI tests complete.
    """
    yield
    # Purge UI modules and mock GI if any
    gi_mod = sys.modules.get("gi")
    is_mock_gi = gi_mod is not None and not hasattr(gi_mod, "__file__")
    to_delete = [
        k
        for k in list(sys.modules.keys())
        if k.startswith("media_toolbox.ui")
        or (
            is_mock_gi
            and (
                k == "gi"
                or k.startswith("gi.")
                or k.startswith("gi_")
                or k in ("gobject", "glib", "gio", "gtk", "gtk.gdk")
            )
        )
    ]
    for k in to_delete:
        sys.modules.pop(k, None)


@pytest.fixture
def sample_video_media_info() -> MediaInfo:
    """Standard 1080p video with AAC audio fixture."""
    v = VideoStream(index=0, codec_name="h264", width=1920, height=1080, fps=30.0, duration=60.0)
    a = AudioStream(index=1, codec_name="aac", channels=2, sample_rate=48000, duration=60.0)
    fmt = FormatInfo(filename="sample.mp4", format_name="mov,mp4,m4a,3gp,3g2,mj2", duration=60.0, size_bytes=15_000_000)
    return MediaInfo(format=fmt, video_streams=(v,), audio_streams=(a,))


@pytest.fixture
def sample_silent_media_info() -> MediaInfo:
    """Silent video with no audio stream."""
    v = VideoStream(index=0, codec_name="h264", width=1280, height=720, fps=24.0, duration=30.0)
    fmt = FormatInfo(filename="silent.mp4", format_name="mp4", duration=30.0, size_bytes=5_000_000)
    return MediaInfo(format=fmt, video_streams=(v,), audio_streams=())
