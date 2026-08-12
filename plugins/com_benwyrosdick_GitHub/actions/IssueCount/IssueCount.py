import urllib.parse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from ..base.GitHubActionBase import GitHubActionBase


# Each combo's options as (settings_value, locale_key). The settings value is a
# stable key stored in the button settings; the locale key resolves to the
# human label shown in the dropdown.
AUTHOR_OPTIONS = [
    ("any", "actions.issue-count.author.any"),
    ("me", "actions.issue-count.author.me"),
    ("not_me", "actions.issue-count.author.not-me"),
    ("user", "actions.issue-count.author.user"),
    ("not_user", "actions.issue-count.author.not-user"),
]
ASSIGNEE_OPTIONS = [
    ("any", "actions.issue-count.assignee.any"),
    ("me", "actions.issue-count.assignee.me"),
    ("not_me", "actions.issue-count.assignee.not-me"),
    ("none", "actions.issue-count.assignee.none"),
]
STATE_OPTIONS = [
    ("open", "actions.issue-count.state.open"),
    ("closed", "actions.issue-count.state.closed"),
    ("all", "actions.issue-count.state.all"),
]

DEFAULTS = {
    "name": "",
    "repo": "",
    "author": "any",
    "user": "",
    "assignee": "any",
    "labels": "",
    "state": "open",
    "extra": "",
}


class IssueCount(GitHubActionBase):
    """Shows a live count of issues matching a configurable filter.

    Pressing the key opens the equivalent GitHub issue search in the browser.
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
        top = name[:12] if name else "Issues"
        # Icon stays centered; the count/status goes in the bottom label so it
        # doesn't sit on top of the icon. Keep the center clear every tick.
        self.set_icon("issue.png", size=0.45)
        self.safe_set_label("top", top, font_size=12)
        self.safe_set_label("center", "", font_size=1)
        # Set the background exactly once per path: setting it twice (a reset
        # here plus a value below) makes it oscillate every tick and flicker.

        if not self._repo(settings):
            self.safe_set_background([0, 0, 0, 0])
            self.safe_set_label("bottom", "—", font_size=16)
            self.show_error(1)
            return

        # When rate limited, stop polling and show a countdown to the reset.
        until = self.plugin_base.rate_limited_until()
        if until is not None:
            self.render_rate_limited(until)
            return

        query = self._build_query(settings)
        count = self.plugin_base.get_count(query)
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
        if not self._repo(settings):
            self.show_error(2)
            return
        query = self._build_query(settings)
        self.plugin_base.invalidate(query)
        self.plugin_base.backend.open_in_browser(self._build_url(query))

    # ------------------------------------------------------------------ #
    # Settings / query building
    # ------------------------------------------------------------------ #
    def _settings(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self.get_settings() or {})
        return merged

    def _repo(self, settings: dict) -> str:
        """A cleaned owner/name, or "" if not a plausible repo."""
        repo = (settings.get("repo") or "").strip().strip("/")
        return repo if repo.count("/") == 1 and all(repo.split("/")) else ""

    def _build_query(self, settings: dict) -> str:
        terms = [f"repo:{self._repo(settings)}", "type:issue"]

        state = settings.get("state", "open")
        if state == "open":
            terms.append("state:open")
        elif state == "closed":
            terms.append("state:closed")
        # "all" -> no state qualifier

        author = settings.get("author", "any")
        user = (settings.get("user") or "").strip().lstrip("@")
        if author == "me":
            terms.append("author:@me")
        elif author == "not_me":
            terms.append("-author:@me")
        elif author == "user" and user:
            terms.append(f"author:{user}")
        elif author == "not_user" and user:
            terms.append(f"-author:{user}")

        assignee = settings.get("assignee", "any")
        if assignee == "me":
            terms.append("assignee:@me")
        elif assignee == "not_me":
            terms.append("-assignee:@me")
        elif assignee == "none":
            terms.append("no:assignee")

        # Comma-separated labels are OR'd via a single qualifier with quoted
        # values (`label:"a","b"`). Separate `label:` qualifiers would AND them.
        labels = [raw.strip() for raw in (settings.get("labels") or "").split(",")]
        labels = [label for label in labels if label]
        if labels:
            terms.append("label:" + ",".join(f'"{label}"' for label in labels))

        extra = (settings.get("extra") or "").strip()
        if extra:
            terms.append(extra)

        return " ".join(terms)

    def _build_url(self, query: str) -> str:
        return (
            "https://github.com/search?q="
            + urllib.parse.quote(query)
            + "&type=issues"
        )

    # ------------------------------------------------------------------ #
    # Configuration UI
    # ------------------------------------------------------------------ #
    def get_config_rows(self) -> list:
        lm = self.plugin_base.lm

        self.name_row = Adw.EntryRow(title=lm.get("actions.issue-count.name-row.label"))
        self.repo_row = Adw.EntryRow(title=lm.get("actions.issue-count.repo.label"))
        self.author_row = self._combo("actions.issue-count.author.label", AUTHOR_OPTIONS)
        self.user_row = Adw.EntryRow(title=lm.get("actions.issue-count.user.label"))
        self.assignee_row = self._combo("actions.issue-count.assignee.label", ASSIGNEE_OPTIONS)
        self.labels_row = Adw.EntryRow(title=lm.get("actions.issue-count.labels.label"))
        self.state_row = self._combo("actions.issue-count.state.label", STATE_OPTIONS)
        self.extra_row = Adw.EntryRow(title=lm.get("actions.issue-count.extra.label"))

        self._rows = [
            self.name_row, self.repo_row, self.author_row, self.user_row,
            self.assignee_row, self.labels_row, self.state_row, self.extra_row,
        ]

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
        self.user_row.connect("changed", self._on_entry_change)
        self.labels_row.connect("changed", self._on_entry_change)
        self.extra_row.connect("changed", self._on_entry_change)
        self.author_row.connect("notify::selected", self._on_combo_change)
        self.assignee_row.connect("notify::selected", self._on_combo_change)
        self.state_row.connect("notify::selected", self._on_combo_change)

    def disconnect_signals(self):
        for row, fn in (
            (self.name_row, self._on_entry_change),
            (self.repo_row, self._on_entry_change),
            (self.user_row, self._on_entry_change),
            (self.labels_row, self._on_entry_change),
            (self.extra_row, self._on_entry_change),
            (self.author_row, self._on_combo_change),
            (self.assignee_row, self._on_combo_change),
            (self.state_row, self._on_combo_change),
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
        self.user_row.set_text(settings["user"])
        self.labels_row.set_text(settings["labels"])
        self.extra_row.set_text(settings["extra"])
        self._select(self.author_row, AUTHOR_OPTIONS, settings["author"])
        self._select(self.assignee_row, ASSIGNEE_OPTIONS, settings["assignee"])
        self._select(self.state_row, STATE_OPTIONS, settings["state"])

    def _select(self, row, options, value):
        keys = [v for v, _ in options]
        row.set_selected(keys.index(value) if value in keys else 0)

    def _on_entry_change(self, *args):
        settings = self.get_settings() or {}
        settings["name"] = self.name_row.get_text()
        settings["repo"] = self.repo_row.get_text()
        settings["user"] = self.user_row.get_text()
        settings["labels"] = self.labels_row.get_text()
        settings["extra"] = self.extra_row.get_text()
        self.set_settings(settings)

    def _on_combo_change(self, *args):
        settings = self.get_settings() or {}
        settings["author"] = AUTHOR_OPTIONS[self.author_row.get_selected()][0]
        settings["assignee"] = ASSIGNEE_OPTIONS[self.assignee_row.get_selected()][0]
        settings["state"] = STATE_OPTIONS[self.state_row.get_selected()][0]
        self.set_settings(settings)
