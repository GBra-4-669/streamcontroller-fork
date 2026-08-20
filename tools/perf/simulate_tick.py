#!/usr/bin/env python3
"""Standalone simulation of a StreamDeckGB media tick on the user's real page.

Loads the real 'home' page config + assets and drives the REAL DeckController
classes (Background, ControllerKey, KeyGIF, LayoutManager, ...) through
on_media_player_tick() for N ticks, reporting per-tick render cost. Used to
find and verify per-tick hotspots without touching the live app / deck.

Usage:
    python3 tools/perf/simulate_tick.py [--ticks 600] [--page home]
"""
import argparse
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PIL import Image

# The app's CLI argparser (globals.py) parses sys.argv at import time; keep the
# simulator's own flags out of it.
_saved_argv = sys.argv
sys.argv = [_saved_argv[0]] if _saved_argv else ["simulate_tick"]

# Minimal app stubs before importing the app module graph.
import globals as gl

gl.settings_manager = types.SimpleNamespace(
    get_app_settings=lambda: {},
    font_defaults={},
)
gl.app = types.SimpleNamespace(
    main_win=types.SimpleNamespace(get_mapped=lambda: False),
)

from src.backend.DeckManagement.DeckController import (
    Background,
    BackgroundVideo,
    ControllerKey,
    ControllerKeyState,
    InputIdentifier,
    KeyGIF,
    TASK_PRIORITY_LOW,
)
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.DeckManagement.Subclasses.KeyImage import InputImage
from src.backend.DeckManagement.Subclasses.KeyLayout import ImageLayout
from src.backend.DeckManagement.HelperMethods import is_image, is_svg, is_video
from src.backend.DeckManagement.DeckController import get_page_media_image

DATA = os.path.expanduser("~/.var/app/com.core447.StreamController/data")
PAGES = os.path.join(DATA, "pages")
ASSETS = os.path.join(DATA, "Assets", "AssetManager", "Assets")


class FakeDeck:
    def key_layout(self):
        return (3, 5)

    def key_count(self):
        return 15

    def key_image_format(self):
        return {"size": (72, 72), "format": "JPEG", "rotation": 0, "flip": (False, False)}

    def get_rotation(self):
        return 0

    def get_serial_number(self):
        return "FAKE-SIM"

    def is_visual(self):
        return True

    def is_open(self):
        return True

    def is_touch(self):
        return False

    def key_states(self):
        return [False] * (self.key_count() + 1)


class FakeScreenSaver:
    showing = False


class FakeMediaPlayer:
    FPS = 30

    def add_image_task(self, *a, **k):
        pass

    def boost_input_priority(self, *a, **k):
        pass


class FakePage:
    action_objects = {}

    def get_all_actions_for_input(self, ident, state):
        return []


class FakeDeckController:
    def __init__(self):
        self.deck = FakeDeck()
        self.key_spacing = (36, 36)
        self.active_page = FakePage()
        self.screen_saver = FakeScreenSaver()
        self.media_player = FakeMediaPlayer()
        self.background = Background(self)
        self.ui_image_changes_while_hidden = {}
        self.inputs = {Input.Key: []}
        self.input_load_executor = None
        self._suppress_render = False

    def get_key_image_size(self):
        return (72, 72)

    def generate_alpha_key(self):
        return Image.new("RGBA", (72, 72), (0, 0, 0, 0))

    def get_own_key_grid(self):
        return None

    def get_alive(self):
        return True

    def is_visual(self):
        return True

    def safe_serial_number(self):
        return "FAKE-SIM"

    def mark_page_ready_to_clear(self, *a):
        pass


def load_key(key, state_dict, media_key, set_image_fn, set_video_fn):
    media = state_dict_media(state_dict, media_key)
    if not media or not media.get("path"):
        return
    path = media["path"]
    if not os.path.isfile(path):
        return
    if is_image(path):
        set_image_fn(InputImage(controller_input=key, image=get_page_media_image(path, False)), update=False)
    elif is_svg(path):
        set_image_fn(InputImage(controller_input=key, image=get_page_media_image(path, True)), update=False)
    elif is_video(path):
        if os.path.splitext(path)[1].lower() == ".gif":
            set_video_fn(KeyGIF(controller_key=key, gif_path=path,
                                loop=media.get("loop", True),
                                fps=media.get("fps", 30), speed=media.get("speed") or 1.0))
        else:
            set_video_fn(None, update=False)


def state_dict_media(state_dict, media_key):
    m = state_dict.get(media_key)
    return m if isinstance(m, dict) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--page", default="home")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="Sleep this many seconds per tick (e.g. 0.033 to mimic the "
                         "30fps media loop, which changes GIF frame-due cadence)")
    args = ap.parse_args()
    sys.argv = _saved_argv

    with open(os.path.join(PAGES, f"{args.page}.json")) as f:
        page_dict = json.load(f)

    dc = FakeDeckController()
    dc.inputs[Input.Key] = [ControllerKey(dc, Input.Key(f"{x}x{y}"))
                            for y in range(3) for x in range(5)]

    # Page background
    bg = page_dict.get("settings", {}).get("background") or {}
    bg_path = bg.get("media-path") or bg.get("path")
    if bg_path and os.path.isfile(bg_path) and is_video(bg_path):
        dc.background.set_video(BackgroundVideo(dc, bg_path, loop=True,
                                                fps=bg.get("fps", 30) or 30,
                                                opacity=bg.get("opacity", 1.0) or 1.0),
                                update=False)

    # Key states from the page config (state 0, like the running app)
    key_by_ident = {k.identifier.json_identifier: k for k in dc.inputs[Input.Key]}
    for ident, input_dict in page_dict.get("keys", {}).items():
        key = key_by_ident.get(ident)
        if key is None:
            continue
        state = key.get_active_state()
        state_dict = input_dict.get("states", {}).get("0", {})
        load_key(key, state_dict, "media", state.set_image, state.set_video)
        load_key(key, state_dict, "media-2", state.set_media_2_image, state.set_media_2_video)
        lm = state.layout_manager
        m = state_dict.get("media") or {}
        if isinstance(m, dict):
            lm.set_page_layout(ImageLayout(fill_mode=m.get("fill-mode"), size=m.get("size"),
                                           valign=m.get("valign"), halign=m.get("halign"),
                                           opacity=m.get("opacity"), speed=m.get("speed"),
                                           blend_mode=m.get("blend-mode")), update=False)
        lm2 = state.media_2_layout_manager
        m2 = state_dict.get("media-2") or {}
        if isinstance(m2, dict):
            lm2.set_page_layout(ImageLayout(fill_mode=m2.get("fill-mode"), size=m2.get("size"),
                                            valign=m2.get("valign"), halign=m2.get("halign"),
                                            opacity=m2.get("opacity"), speed=m2.get("speed"),
                                            blend_mode=m2.get("blend-mode")), update=False)
        bc = state_dict.get("background") or {}
        if isinstance(bc, dict) and bc.get("color"):
            state.background_manager.set_page_color(bc["color"], update=False)

    # Warm up GIF frame caches (decode every frame once) + bg cache
    print("Warming caches ...", file=sys.stderr)
    for _ in range(120):
        dc.background.update_tiles()
        for key in dc.inputs[Input.Key]:
            key.on_media_player_tick()

    # Measure
    n_bg = max(1, dc.media_player.FPS // (dc.background.video.fps if dc.background.video else 1))
    tick_times = []
    per_key = {k.identifier.json_identifier: {"time": 0.0, "renders": 0, "updates": 0} for k in dc.inputs[Input.Key]}
    for i in range(args.ticks):
        t0 = time.perf_counter()
        if dc.background.video is not None:
            if i % n_bg == 0:
                dc.background.update_tiles()
        for key in dc.inputs[Input.Key]:
            kt0 = time.perf_counter()
            before = key.media_ticks
            key.on_media_player_tick()
            ident = key.identifier.json_identifier
            per_key[ident]["time"] += (time.perf_counter() - kt0) * 1000
            per_key[ident]["updates"] += 1
            if key.media_ticks > before:
                pass
            # count actual renders via the last-img-hash
            if key._last_img_hash is not None and getattr(key, "_prev_hash", None) != key._last_img_hash:
                per_key[ident]["renders"] += 1
            key._prev_hash = key._last_img_hash
        tick_times.append((time.perf_counter() - t0) * 1000)
        if args.pace > 0.0:
            time.sleep(args.pace)

    tick_ms = sum(tick_times) / len(tick_times)
    print(f"ticks={args.ticks} avg_tick={tick_ms:.2f} ms  "
          f"max_tick={max(tick_times):.2f} ms  "
          f"est_core_30fps={tick_ms * 30 / 10:.1f}%")

    for ident in sorted(per_key, key=lambda i: -per_key[i]["time"]):
        d = per_key[ident]
        state = next(k for k in dc.inputs[Input.Key] if k.identifier.json_identifier == ident).get_active_state()
        kinds = []
        if state.key_video is not None:
            kinds.append(type(state.key_video).__name__)
        if state.key_image is not None:
            kinds.append("Image")
        if state.media_2_video is not None:
            kinds.append("m2:" + type(state.media_2_video).__name__)
        if state.media_2_image is not None:
            kinds.append("m2:Image")
        if next(k for k in dc.inputs[Input.Key] if k.identifier.json_identifier == ident)._get_uses_blend(state):
            kinds.append("BLEND")
        print(f"  {ident}: {d['time']/args.ticks*1000:6.1f} us/tick  renders={d['renders']}  "
              f"({', '.join(kinds) or 'empty'})")


if __name__ == "__main__":
    main()
