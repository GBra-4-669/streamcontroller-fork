from GtkHelper.ComboRow import SimpleComboRowItem
from GtkHelper.GenerativeUI.ComboRow import ComboRow
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.PluginManager.PluginBase import PluginBase

import time
import os
import psutil
from threading import Lock

# Import gtk modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

class CPUTemp(ActionBase):
    _temperature_cache = None
    _temperature_cache_at = 0.0
    _temperature_cache_lock = Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = False
        self._last_displayed = None

        self.unit_row = ComboRow(
            action_core=self,
            var_name="unit",
            default_value="C",
            items=[SimpleComboRowItem("C", "°C"), SimpleComboRowItem("F", "°F")],
            title="Unit",
            can_reset=False,
            on_change=lambda *args: self.update()
        )
    
    def on_ready(self):
        self.update()
        
    def on_tick(self):
        self.update()

    def celcius_to_fahrenheit(self, celsius):
        return celsius * 1.8 + 32

    def update(self):
        now = time.monotonic()
        with type(self)._temperature_cache_lock:
            if now - type(self)._temperature_cache_at >= 1.0:
                type(self)._temperature_cache = psutil.sensors_temperatures()
                type(self)._temperature_cache_at = now
            temperature = type(self)._temperature_cache

        if temperature is None:
            if self._last_displayed != "N/A":
                self.set_center_label(text="N/A", font_size=18)
                self._last_displayed = "N/A"
            return

        # intel cpu
        if "coretemp" in temperature:
            temperature = temperature.get("coretemp")[0].current
        # amd cpu
        elif "k10temp" in temperature:
            temperature = temperature.get("k10temp")
            if len(temperature) > 1:
                # zen chips and newer, Tccd1
                temperature = temperature[1].current
            else:
                # amd chips before zen, or if only Tctl is returned
                temperature = temperature[0].current
        else:
            self.set_center_label(text="N/A", font_size=18)
            return

        unit_key = self.unit_row.get_value()
        temp = int(temperature)
        if unit_key == "F":
            temp = self.celcius_to_fahrenheit(temp)
        displayed = f"{round(temp)} °{unit_key}"
        if displayed != self._last_displayed:
            self.set_center_label(text=displayed, font_size=18)
            self._last_displayed = displayed