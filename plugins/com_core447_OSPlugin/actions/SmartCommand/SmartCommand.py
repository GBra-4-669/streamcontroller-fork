import os
import signal
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from src.backend.PluginManager.ActionBase import ActionBase


class SmartCommand(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._running = False
        self._lock = threading.Lock()
        self._result_timer_id = None

    def get_config_rows(self) -> list:
        command_entry = Adw.EntryRow(title="Command")
        command_entry.set_text(self.get_settings().get("command", ""))
        command_entry.connect("changed", self._command_changed)
        timeout_row = Adw.SpinRow.new_with_range(1, 300, 1)
        timeout_row.set_title("Command timeout (seconds)")
        timeout_row.set_value(self.get_settings().get("timeout", 3))
        timeout_row.connect("changed", self._timeout_changed)
        duration_row = Adw.SpinRow.new_with_range(1, 60, 1)
        duration_row.set_title("Result indicator duration (seconds)")
        duration_row.set_value(self.get_settings().get("result_duration", 3))
        duration_row.connect("changed", self._duration_changed)
        return [command_entry, timeout_row, duration_row]

    def _command_changed(self, entry, *_args):
        settings = self.get_settings()
        settings["command"] = entry.get_text()
        self.set_settings(settings)

    def _timeout_changed(self, row):
        settings = self.get_settings()
        settings["timeout"] = int(row.get_value())
        self.set_settings(settings)

    def _duration_changed(self, row):
        settings = self.get_settings()
        settings["result_duration"] = int(row.get_value())
        self.set_settings(settings)

    def on_ready(self):
        self._set_idle_ui()

    def on_key_down(self):
        with self._lock:
            if self._running:
                return
            self._running = True
        self.set_border_color((255, 200, 0, 255))
        self.set_center_label("WAIT")
        command = self.get_settings().get("command", "").strip()
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    def _run_command(self, command):
        try:
            if not command:
                result = (1, "", "No command configured")
            else:
                process = subprocess.Popen(
                    command, shell=True, start_new_session=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    stdout, stderr = process.communicate(
                        timeout=max(1, int(self.get_settings().get("timeout", 3)))
                    )
                    result = (process.returncode, stdout.strip(), stderr.strip())
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    stdout, _stderr = process.communicate()
                    result = (124, stdout.strip(), "Command timed out")
        except OSError as error:
            result = (1, "", str(error))
        GLib.idle_add(self._apply_result, result)

    def _apply_result(self, result):
        with self._lock:
            self._running = False
        returncode, stdout, stderr = result
        self.set_border_color((0, 255, 0, 255) if returncode == 0 else (255, 0, 0, 255))
        self.set_center_label((stdout or "OK") if returncode == 0 else (stderr or "ERR"))
        self._result_timer_id = GLib.timeout_add_seconds(
            max(1, int(self.get_settings().get("result_duration", 3))),
            self._clear_result,
        )
        return GLib.SOURCE_REMOVE

    def _clear_result(self):
        self._result_timer_id = None
        self._set_idle_ui()
        return GLib.SOURCE_REMOVE

    def _set_idle_ui(self):
        self.set_border_color(None)
        self.hide_overlay()
        self.set_center_label(None)
