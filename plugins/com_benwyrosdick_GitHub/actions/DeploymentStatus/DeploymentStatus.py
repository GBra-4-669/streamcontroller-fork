import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from ..base.GitHubActionBase import GitHubActionBase


class DeploymentStatus(GitHubActionBase):
    PENDING = {"pending", "in_progress", "queued"}
    TERMINAL = {"success", "failure", "error", "inactive"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._watching = False
        self._blink = False
        self._blink_timer_id = None
    def _shared(self):
        settings = self.get_settings()
        self._watch_key = (
            settings.get("owner", "").strip().lower(),
            settings.get("repo", "").strip().lower(),
            settings.get("environment", "production").strip().lower() or "production",
            int(settings.get("timeout_seconds", 600)),
            max(3, int(settings.get("poll_interval_seconds", 10))),
        )
        watchers = self.plugin_base.deployment_watchers
        return watchers.setdefault(self._watch_key, {
            "state": "idle",
            "cancel": threading.Event(),
        })

    def get_config_rows(self) -> list:
        rows = []
        for key, title, default in (
            ("owner", "Owner", ""),
            ("repo", "Repository", ""),
            ("environment", "Environment", "production"),
        ):
            row = Adw.EntryRow(title=title)
            row.set_text(self.get_settings().get(key, default))
            row.connect("changed", self._setting_changed, key)
            rows.append(row)

        self.timeout_row = Adw.SpinRow.new_with_range(1, 3600, 1)
        self.timeout_row.set_title("Timeout (seconds)")
        self.timeout_row.set_value(self.get_settings().get("timeout_seconds", 600))
        self.timeout_row.connect("changed", self._number_changed, "timeout_seconds")
        rows.append(self.timeout_row)

        self.poll_row = Adw.SpinRow.new_with_range(3, 300, 1)
        self.poll_row.set_title("Poll interval (seconds)")
        self.poll_row.set_value(self.get_settings().get("poll_interval_seconds", 10))
        self.poll_row.connect("changed", self._number_changed, "poll_interval_seconds")
        rows.append(self.poll_row)
        return rows

    def _setting_changed(self, row, key):
        settings = self.get_settings()
        settings[key] = row.get_text().strip()
        self.set_settings(settings)

    def _number_changed(self, row, key):
        settings = self.get_settings()
        settings[key] = int(row.get_value())
        self.set_settings(settings)

    def on_ready(self):
        state = self._shared()["state"]
        if state == "idle":
            self._set_idle()
        else:
            self._render(state)

    def on_tick(self):
        state = self._shared()["state"]
        self._render(state)

    def on_key_down(self):
        with self._lock:
            shared = self._shared()
            if shared["state"] in {"pending", "in_progress", "queued"}:
                shared["cancel"].set()
                shared["state"] = "idle"
                self._watching = False
                GLib.idle_add(self._set_idle)
                return
            if shared["state"] in {
                "success", "failure", "error", "inactive",
                "no_deployment", "timeout", "auth",
            }:
                shared["state"] = "idle"
                GLib.idle_add(self._set_idle)
                return
            self._watching = True
            shared["cancel"] = threading.Event()
            shared["state"] = "pending"
            trigger_key = (
                self.get_settings().get("owner", "").strip().lower(),
                self.get_settings().get("repo", "").strip().lower(),
                self.get_settings().get("environment", "production").strip().lower() or "production",
            )
            shared["wait_for_new"] = trigger_key in self.plugin_base.deployment_auto_triggers
            self.plugin_base.deployment_auto_triggers.discard(trigger_key)
            self._cancel = shared["cancel"]
        self._render("pending")
        threading.Thread(target=self._watch, daemon=True, name="github-deployment-watch").start()

    def _watch(self):
        settings = self.get_settings()
        owner = settings.get("owner", "").strip()
        repo = settings.get("repo", "").strip()
        environment = settings.get("environment", "production").strip() or "production"
        timeout = max(1, int(settings.get("timeout_seconds", 600)))
        interval = max(3, int(settings.get("poll_interval_seconds", 10)))
        if not owner or not repo:
            GLib.idle_add(self._render, "no_deployment")
            return

        deployment_id, error = self._gh(
            f"repos/{owner}/{repo}/deployments?environment={environment}&per_page=1",
            ".[0].id",
        )
        if error or not deployment_id:
            GLib.idle_add(self._render, "auth" if error else "no_deployment")
            return

        started = time.monotonic()
        if self._shared().get("wait_for_new"):
            baseline_id = deployment_id
            deployment_id = ""
            while not self._cancel.is_set() and time.monotonic() - started < timeout:
                deployment_id, error = self._gh(
                    f"repos/{owner}/{repo}/deployments?environment={environment}&per_page=1",
                    ".[0].id",
                )
                if error:
                    GLib.idle_add(self._render, "auth")
                    return
                if deployment_id and deployment_id != baseline_id:
                    break
                self._cancel.wait(interval)
            if not deployment_id or deployment_id == baseline_id:
                GLib.idle_add(self._render, "timeout")
                return
        while not self._cancel.is_set():
            if time.monotonic() - started >= timeout:
                GLib.idle_add(self._render, "timeout")
                return
            state, error = self._gh(
                f"repos/{owner}/{repo}/deployments/{deployment_id}/statuses?per_page=1",
                ".[0].state",
            )
            if error:
                GLib.idle_add(self._render, "auth")
                return
            state = (state or "pending").lower()
            GLib.idle_add(self._render, state if state in self.PENDING | self.TERMINAL else "pending")
            if state in self.TERMINAL:
                return
            self._cancel.wait(interval)

    @staticmethod
    def _gh(endpoint, query):
        result = subprocess.run(
            ["gh", "api", endpoint, "--jq", query],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return "", result.stderr.strip()
        return result.stdout.strip(), ""

    def _render(self, state):
        shared = self._shared()
        if state != "idle":
            shared["state"] = state
        with self._lock:
            if state == "idle":
                self._watching = False
        if state in self.PENDING:
            self.set_status_badge((255, 200, 0, 255))
            self.safe_set_label("center", "", font_size=1)
        elif state == "success":
            self.set_status_badge((0, 255, 0, 255))
            self.safe_set_label("center", "", font_size=1)
        elif state in {"failure", "error"}:
            self.set_status_badge((255, 0, 0, 255))
            self.safe_set_label("center", "", font_size=1)
        elif state == "inactive":
            self.set_status_badge((128, 128, 128, 255))
            self.safe_set_label("center", "", font_size=1)
        elif state == "no_deployment":
            self.set_status_badge((128, 128, 128, 255))
            self.set_top_label("N/A", font_size=14, update=False)
            self.get_input().update()
        elif state == "timeout":
            self._blink = not self._blink
            self.set_status_badge((128, 128, 128, 255) if self._blink else None)
            self.set_top_label("TO", font_size=14, update=False)
            self.get_input().update()
            if self._blink_timer_id is None:
                self._blink_timer_id = GLib.timeout_add(500, self._blink_timeout)
        elif state == "auth":
            self.set_status_badge((40, 100, 220, 255))
            self.set_top_label("AUTH", font_size=12, update=False)
            self.get_input().update()
        elif state == "idle":
            self._set_idle()
        self.commit_render()
        return GLib.SOURCE_REMOVE

    def _blink_timeout(self):
        self._blink_timer_id = None
        if self._shared()["state"] == "timeout":
            self._render("timeout")
        return GLib.SOURCE_REMOVE

    def _set_idle(self):
        self._cancel.set()
        self._watching = False
        self._shared()["state"] = "idle"
        self.set_status_badge(None)
        self.safe_set_label("center", "", font_size=1)
        self.commit_render()
        return GLib.SOURCE_REMOVE
