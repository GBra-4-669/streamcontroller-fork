import os
import time

from src.backend.PluginManager.ActionBase import ActionBase


def format_countdown(seconds: float) -> str:
    """Compact mm/ss countdown, e.g. 205s -> "3m25s", 9s -> "9s"."""
    secs = max(0, int(seconds))
    minutes, secs = divmod(secs, 60)
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class GitHubActionBase(ActionBase):
    """Shared rendering and error helpers for GitHub actions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Last value applied for each visual property, so render() (which runs
        # every tick) only re-applies a property when it actually changes.
        self._render_state = {}
        # Whether this render pass changed anything that needs pushing to the
        # deck. Each setter defers its push (update=False); we do ONE update at
        # the end (commit_render). Pushing per-setter flashes the key through
        # intermediate states — that was the flicker.
        self._render_dirty = False

    def reset_render_state(self):
        """Forget cached visuals so the next render re-applies everything.
        Call from on_ready so a freshly (re)loaded key always paints."""
        self._render_state = {}
        self._render_dirty = False

    def commit_render(self):
        """Push one composited image to the deck, only if this render changed
        something. Called once after render() so all the per-property updates
        coalesce into a single, flicker-free update."""
        if not self._render_dirty:
            return
        self._render_dirty = False
        try:
            self.get_input().update()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Rendering helpers (deduped + deferred — see commit_render)
    # ------------------------------------------------------------------ #
    def set_icon(self, name: str, size: float = 0.75):
        if self._render_state.get("icon") == (name, size):
            return
        self._render_state["icon"] = (name, size)
        self._render_dirty = True
        path = os.path.join(self.plugin_base.PATH, "assets", name)
        try:
            self.set_media(media_path=path, size=size, update=False)
        except (AttributeError, TypeError):
            self.set_media(media_path=path, size=size)

    def clear_icon(self):
        # Drop any previously-set icon so a label-only key isn't covered by it.
        if self._render_state.get("icon") is None:
            return
        self._render_state["icon"] = None
        self._render_dirty = True
        try:
            self.set_media(media_path=None, update=False)
        except (AttributeError, TypeError):
            pass

    def safe_set_background(self, color):
        if self._render_state.get("bg") == color:
            return
        self._render_state["bg"] = color
        self._render_dirty = True
        # set_background_color raises AttributeError on some 1.5.0-beta builds.
        try:
            self.set_background_color(color=color, update=False)
        except (AttributeError, TypeError):
            try:
                self.set_background_color(color=color)
            except AttributeError:
                pass

    def safe_set_label(self, position: str, text: str, **kwargs):
        """Set a label defensively, deferring the deck push and skipping no-ops.

        Only set_bottom_label is exercised by every build we target; the top /
        center setters exist in current StreamController but we guard them so a
        missing method degrades gracefully instead of crashing render().
        """
        state_key = ("label", position)
        value = (text, tuple(sorted(kwargs.items())))
        if self._render_state.get(state_key) == value:
            return
        self._render_state[state_key] = value
        self._render_dirty = True
        setter = getattr(self, f"set_{position}_label", None)
        if setter is None:
            return
        try:
            setter(text, update=False, **kwargs)
        except (AttributeError, TypeError):
            try:
                setter(text)
            except Exception:
                pass

    def show_error(self, *args, **kwargs):
        # Deduped: re-showing/clearing the error overlay recomposites the whole
        # key (and flickers the background), so only call through on a change.
        state = ("show", args, tuple(sorted(kwargs.items())))
        if self._render_state.get("error") == state:
            return
        self._render_state["error"] = state
        try:
            super().show_error(*args, **kwargs)
        except Exception:
            pass

    def hide_error(self):
        if self._render_state.get("error") == ("hide",):
            return
        self._render_state["error"] = ("hide",)
        try:
            super().hide_error()
        except Exception:
            pass

    def render_rate_limited(self, until: float):
        """Shared "rate limit" key state: red background, no icon, and a
        countdown (bottom) to when polling will resume."""
        self.clear_icon()
        self.safe_set_background([180, 30, 30, 255])
        self.safe_set_label("top", "rate limit", font_size=12)
        self.safe_set_label("center", "", font_size=1)
        self.safe_set_label("bottom", format_countdown(until - time.time()), font_size=14)

    def render(self):
        """Update the button from current state. Overridden per action."""
        raise NotImplementedError
