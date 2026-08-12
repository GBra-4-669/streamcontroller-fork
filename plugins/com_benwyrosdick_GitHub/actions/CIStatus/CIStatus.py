import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from ..base.GitHubActionBase import GitHubActionBase


DEFAULTS = {
    "name": "",
    "repo": "",
    "workflow": "",
    "branch": "",
}

# Icon shown for each classified run state.
ICONS = {
    "success": "ci_success.png",
    "failure": "ci_failure.png",
    "running": "ci_running.gif",   # spinning amber arrow (actively in progress)
    "queued": "ci_queued.png",     # grey dots (queued / waiting to start)
    "neutral": "ci_neutral.png",
}


def classify(run: dict) -> str:
    """Collapse a run's status/conclusion into success/failure/running/queued/neutral."""
    status = run.get("status")
    if status == "in_progress":
        return "running"
    if status and status != "completed":
        # queued / waiting / requested / pending — not started running yet
        return "queued"
    conclusion = run.get("conclusion")
    if conclusion == "success":
        return "success"
    if conclusion in ("failure", "timed_out", "startup_failure"):
        return "failure"
    # cancelled / skipped / neutral / action_required / stale / unknown
    return "neutral"


class CIStatus(GitHubActionBase):
    """Shows the status of the latest GitHub Actions run for a repo.

    Optionally pinned to a workflow and/or branch; when no branch is set it
    follows the repo's default branch. Pressing the key opens the run (or the
    repo's Actions page) in the browser.
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
        self.render()
        self.commit_render()

    def render(self):
        settings = self._settings()
        name = settings["name"].strip()
        top = name[:12] if name else "CI"
        repo = self._repo(settings)
        # center/bottom labels are only used by the auth / rate-limit states.
        self.safe_set_label("center", "", font_size=1)
        self.safe_set_label("bottom", "", font_size=1)
        # Set the background exactly once per path (setting it twice makes it
        # oscillate every tick and flicker).

        if not repo:
            self.safe_set_background([0, 0, 0, 0])
            self.set_icon("ci_neutral.png", size=0.45)
            self.safe_set_label("top", top, font_size=12)
            self.show_error(1)
            return

        # When rate limited, stop polling and show a countdown to the reset.
        until = self.plugin_base.rate_limited_until()
        if until is not None:
            self.render_rate_limited(until)
            return

        # Every remaining (non-rate-limited) state uses a transparent background.
        self.safe_set_background([0, 0, 0, 0])
        branch = self._effective_branch(settings)
        run = self.plugin_base.get_run(repo, settings["workflow"], branch)
        if run is None:
            # No data yet (run still loading).
            # Show the loading icon, unless gh isn't authenticated.
            if self.plugin_base.get_gh_available() is False:
                self.clear_icon()
                self.safe_set_label("center", "auth", font_size=14)
                self.show_error(1)
            else:
                self.set_icon("ci_queued.png", size=0.45)
            self.safe_set_label("top", top, font_size=12)
            return

        self.hide_error()
        if run == {}:
            self.set_icon("ci_neutral.png", size=0.45)
            top = name or "no runs"
            self.safe_set_label("top", top[:12], font_size=12)
            return

        state = classify(run)
        self.set_icon(ICONS[state], size=0.45)
        top = name or run.get("workflowName") or branch
        self.safe_set_label("top", (top or "CI")[:12], font_size=12)

        # While actively running, show live step progress, e.g. "4 / 9".
        if state == "running":
            run_id = run.get("databaseId")
            progress = self.plugin_base.get_run_progress(repo, run_id) if run_id else None
            if progress:
                done, total = progress
                self.safe_set_label("bottom", f"{done} / {total}", font_size=14)

    def on_key_down(self):
        settings = self._settings()
        repo = self._repo(settings)
        if not repo:
            self.show_error(2)
            return
        branch = self._effective_branch(settings)
        url = f"https://github.com/{repo}/actions"
        run = self.plugin_base.get_run(repo, settings["workflow"], branch)
        if run:
            url = run.get("url") or url
        self.plugin_base.invalidate_run(repo, settings["workflow"], branch)
        self.plugin_base.backend.open_in_browser(url)

    # ------------------------------------------------------------------ #
    # Settings helpers
    # ------------------------------------------------------------------ #
    def _settings(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self.get_settings() or {})
        return merged

    def _repo(self, settings: dict) -> str:
        repo = (settings.get("repo") or "").strip().strip("/")
        return repo if repo.count("/") == 1 and all(repo.split("/")) else ""

    def _effective_branch(self, settings: dict) -> str:
        """The branch to filter runs on. A blank Branch field means "any
        branch" (returned as ""), so a run on a feature branch is still
        surfaced rather than only runs on the repo's default branch."""
        return (settings.get("branch") or "").strip()

    # ------------------------------------------------------------------ #
    # Configuration UI
    # ------------------------------------------------------------------ #
    def get_config_rows(self) -> list:
        lm = self.plugin_base.lm
        self.name_row = Adw.EntryRow(title=lm.get("actions.ci-status.name-row.label"))
        self.repo_row = Adw.EntryRow(title=lm.get("actions.ci-status.repo.label"))
        self.workflow_row = Adw.EntryRow(title=lm.get("actions.ci-status.workflow.label"))
        self.branch_row = Adw.EntryRow(title=lm.get("actions.ci-status.branch.label"))

        self._rows = [self.name_row, self.repo_row, self.workflow_row, self.branch_row]
        self.load_configs()
        self.connect_signals()
        return self._rows

    def connect_signals(self):
        for row in self._rows:
            row.connect("changed", self._on_change)

    def disconnect_signals(self):
        for row in self._rows:
            try:
                row.disconnect_by_func(self._on_change)
            except TypeError:
                pass

    def load_configs(self):
        self.disconnect_signals()
        settings = self._settings()
        self.name_row.set_text(settings["name"])
        self.repo_row.set_text(settings["repo"])
        self.workflow_row.set_text(settings["workflow"])
        self.branch_row.set_text(settings["branch"])

    def _on_change(self, *args):
        settings = self.get_settings() or {}
        settings["name"] = self.name_row.get_text()
        settings["repo"] = self.repo_row.get_text()
        settings["workflow"] = self.workflow_row.get_text()
        settings["branch"] = self.branch_row.get_text()
        self.set_settings(settings)
