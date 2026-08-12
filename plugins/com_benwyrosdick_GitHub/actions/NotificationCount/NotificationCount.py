import urllib.parse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from ..base.GitHubActionBase import GitHubActionBase


# Notification filters mirroring the inbox's Filters sidebar. Each maps to how
# the count is fetched (`participating` API param + client-side `reason`) and to
# the site's inbox `query` used when opening in the browser. The REST API can't
# filter by reason, so those are selected client-side; "Participating" uses the
# native participating param. Site queries hyphenate multi-word reasons
# (team-mention) where the API uses underscores (team_mention).
FILTERS = {
    "all":              {"reason": "",                 "participating": False, "query": ""},
    "assigned":         {"reason": "assign",           "participating": False, "query": "reason:assign"},
    "participating":    {"reason": "",                 "participating": True,  "query": "reason:participating"},
    "mentioned":        {"reason": "mention",          "participating": False, "query": "reason:mention"},
    "team_mentioned":   {"reason": "team_mention",     "participating": False, "query": "reason:team-mention"},
    "review_requested": {"reason": "review_requested", "participating": False, "query": "reason:review-requested"},
}

# (settings_value, locale_key), in the same order the site lists them. The
# settings value is a stable key stored in the button settings; the locale key
# resolves to the human label shown in the dropdown.
FILTER_OPTIONS = [
    ("all", "actions.notification-count.filter.all"),
    ("assigned", "actions.notification-count.filter.assigned"),
    ("participating", "actions.notification-count.filter.participating"),
    ("mentioned", "actions.notification-count.filter.mentioned"),
    ("team_mentioned", "actions.notification-count.filter.team-mentioned"),
    ("review_requested", "actions.notification-count.filter.review-requested"),
]

DEFAULTS = {
    "name": "",
    "repo": "",
    "filter": "all",
}


class NotificationCount(GitHubActionBase):
    """Shows a live count of unread GitHub notifications.

    Optionally scoped to a single repo and to a common inbox filter (assigned,
    participating, mentioned, team mentioned, review requested). Pressing the
    key opens the matching GitHub notifications inbox view.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def on_ready(self):
        self.reset_render_state()
        self.render()
        self.commit_render()

    def on_tick(self):
        # The count refreshes asynchronously in the plugin; polling here picks
        # up the new value within ~1s of the background fetch completing.
        self.render()
        self.commit_render()

    def render(self):
        settings = self._settings()
        name = settings["name"].strip()
        top = name[:12] if name else "Inbox"
        # Icon stays centered; the count/status goes in the bottom label so it
        # doesn't sit on top of the icon. Keep the center clear every tick.
        self.set_icon("inbox.png", size=0.45)
        self.safe_set_label("top", top, font_size=12)
        self.safe_set_label("center", "", font_size=1)
        # Set the background exactly once per path: setting it twice (a reset
        # here plus a value below) makes it oscillate every tick and flicker.

        # When rate limited, stop polling and show a countdown to the reset.
        until = self.plugin_base.rate_limited_until()
        if until is not None:
            self.render_rate_limited(until)
            return

        repo = self._repo(settings)
        flt = self._filter(settings)
        count = self.plugin_base.get_notification_count(
            repo, flt["participating"], flt["reason"]
        )
        if count is None:
            # No value to show yet. Distinguish "not authenticated" from a
            # transient/loading state so a flaky auth check can't hide a count
            # we've already fetched (that path keeps the last good value).
            self.safe_set_background([0, 0, 0, 0])
            if self.plugin_base.get_gh_available() is False:
                self.safe_set_label("bottom", "auth", font_size=14)
            else:
                self.safe_set_label("bottom", "...", font_size=16)
            self.show_error(1)
            return

        self.hide_error()
        self.safe_set_label("bottom", str(count), font_size=18)
        # Subtle nudge: highlight when there is something to look at.
        self.safe_set_background([40, 70, 120, 255] if count > 0 else [0, 0, 0, 0])

    def on_key_down(self):
        settings = self._settings()
        repo = self._repo(settings)
        flt = self._filter(settings)
        self.plugin_base.invalidate_notification_count(
            repo, flt["participating"], flt["reason"]
        )
        self.plugin_base.backend.open_in_browser(self._build_url(repo, flt))

    # ------------------------------------------------------------------ #
    # Settings / URL building
    # ------------------------------------------------------------------ #
    def _settings(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self.get_settings() or {})
        return merged

    def _repo(self, settings: dict) -> str:
        """A cleaned owner/name, or "" if not a plausible repo (optional here)."""
        repo = (settings.get("repo") or "").strip().strip("/")
        return repo if repo.count("/") == 1 and all(repo.split("/")) else ""

    def _filter(self, settings: dict) -> dict:
        return FILTERS.get(settings.get("filter"), FILTERS["all"])

    def _build_url(self, repo: str, flt: dict) -> str:
        # The inbox page filters via a single `query` param combining repo and
        # reason qualifiers, e.g. `repo:owner/name reason:review-requested`.
        parts = []
        if repo:
            parts.append(f"repo:{repo}")
        if flt["query"]:
            parts.append(flt["query"])
        base = "https://github.com/notifications"
        if parts:
            return base + "?query=" + urllib.parse.quote(" ".join(parts))
        return base

    # ------------------------------------------------------------------ #
    # Configuration UI
    # ------------------------------------------------------------------ #
    def get_config_rows(self) -> list:
        lm = self.plugin_base.lm

        self.name_row = Adw.EntryRow(title=lm.get("actions.notification-count.name-row.label"))
        self.repo_row = Adw.EntryRow(title=lm.get("actions.notification-count.repo.label"))
        self.filter_row = self._combo("actions.notification-count.filter.label", FILTER_OPTIONS)

        self._rows = [self.name_row, self.repo_row, self.filter_row]

        self.load_configs()
        self.connect_signals()
        return self._rows

    def _combo(self, title_key, options):
        model = Gtk.StringList()
        for _value, label_key in options:
            model.append(self.plugin_base.lm.get(label_key))
        return Adw.ComboRow(model=model, title=self.plugin_base.lm.get(title_key))

    # --- signal wiring ------------------------------------------------- #
    def connect_signals(self):
        self.name_row.connect("changed", self._on_entry_change)
        self.repo_row.connect("changed", self._on_entry_change)
        self.filter_row.connect("notify::selected", self._on_combo_change)

    def disconnect_signals(self):
        for row, fn in (
            (self.name_row, self._on_entry_change),
            (self.repo_row, self._on_entry_change),
            (self.filter_row, self._on_combo_change),
        ):
            try:
                row.disconnect_by_func(fn)
            except TypeError:
                pass

    # --- load / save --------------------------------------------------- #
    def load_configs(self):
        self.disconnect_signals()
        settings = self._settings()
        self.name_row.set_text(settings["name"])
        self.repo_row.set_text(settings["repo"])
        self._select(self.filter_row, FILTER_OPTIONS, settings["filter"])

    def _select(self, row, options, value):
        keys = [v for v, _ in options]
        row.set_selected(keys.index(value) if value in keys else 0)

    def _on_entry_change(self, *args):
        settings = self.get_settings() or {}
        settings["name"] = self.name_row.get_text()
        settings["repo"] = self.repo_row.get_text()
        self.set_settings(settings)

    def _on_combo_change(self, *args):
        settings = self.get_settings() or {}
        settings["filter"] = FILTER_OPTIONS[self.filter_row.get_selected()][0]
        self.set_settings(settings)
