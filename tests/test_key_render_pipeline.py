"""Unit tests for the deck-level frame pipeline in DeckController.

Covers the two new mechanisms that keep animated decks cheap:

* the shared decoded-GIF-frame cache (KeyGIF must decode each frame once,
  not once per media tick, and the cache must bound its memory),
* the cached key content layer (media + labels composited once per content
  change) being pixel-identical to the direct per-render composition for
  plain source-over keys.

These tests use small synthetic images and lightweight stand-ins; they do not
construct a DeckController.
"""
import os
import sys
import tempfile
import time
import unittest

from PIL import Image, ImageDraw

# The app's CLI argparser (globals.py) parses sys.argv at import time - strip
# unittest's own flags so the module graph loads under `unittest discover`.
_saved_argv = sys.argv
sys.argv = [_saved_argv[0]] if _saved_argv else ["unittest"]

import globals  # noqa: F401 - resolves the app module import order

sys.argv = _saved_argv

# BackgroundVideoCache reads settings for its disk-cache toggle; stub it so the
# tests run without a full app bootstrap.
import types

globals.settings_manager = types.SimpleNamespace(get_app_settings=lambda: {}, font_defaults={})

from src.backend.DeckManagement import DeckController as dc
from src.backend.DeckManagement.DeckController import (
    _GIF_FRAME_CACHE,
    BackgroundVideo,
    KeyGIF,
    LayoutManager,
)
from src.backend.DeckManagement.Subclasses.KeyLayout import ImageLayout
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.DeckManagement.blend_modes import blend


def make_gif(path, frames=5, size=(64, 64)):
    """Write a small looping RGBA GIF (each frame a distinct color block)."""
    imgs = []
    for i in range(frames):
        img = Image.new("RGBA", size, (20 + i * 40, 30, 40, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((8, 8, size[0] - 8, size[1] - 8), fill=(i * 30 % 255, 200, 100, 200))
        imgs.append(img)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=40, loop=0)


class FakeControllerKey:
    """Minimal stand-in for ControllerKey: only what KeyGIF touches."""

    def __init__(self):
        self.deck_controller = None


class FakeKeyInput:
    """Minimal stand-in for ControllerInput: what LayoutManager touches."""

    def __init__(self, identifier=None):
        self.identifier = identifier if identifier is not None else Input.Key("0x0")
        self.deck_controller = None

    def _mark_content_dirty(self):
        pass


class GifFrameCacheTest(unittest.TestCase):
    def test_frames_decoded_once_and_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.gif")
            make_gif(path, frames=4)
            key = FakeControllerKey()
            gif = KeyGIF(controller_key=key, gif_path=path, fps=10, loop=True)

            first = [gif.get_next_frame() for _ in range(4)]  # decode pass
            gif2 = KeyGIF(controller_key=key, gif_path=path, fps=10, loop=True)
            second = [gif2.get_next_frame() for _ in range(4)]  # should be cache hits

            for f1, f2 in zip(first, second):
                self.assertIs(f1, f2, "frames must be shared between KeyGIF instances")
                self.assertEqual(f1.mode, "RGBA")

            gif.close()
            gif2.close()

    def test_loop_returns_cached_first_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.gif")
            make_gif(path, frames=3)
            gif = KeyGIF(controller_key=FakeControllerKey(), gif_path=path, fps=10, loop=True)
            f0 = gif.get_next_frame()
            gif.get_next_frame()
            gif.get_next_frame()
            wrapped = gif.get_next_frame()  # loops back to frame 0
            self.assertIs(f0, wrapped)
            gif.close()

    def test_eviction_bounds_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big.gif")
            # Small budget so we can force eviction with a few frames.
            make_gif(path, frames=3, size=(64, 64))
            gif = KeyGIF(controller_key=FakeControllerKey(), gif_path=path, fps=10, loop=True)

            # A 3-frame 64x64 GIF is ~12k pixels; temporarily shrink the budget
            # below one frame to prove eviction happens and the cache stays
            # within budget.
            original_max = _GIF_FRAME_CACHE._max_pixels
            try:
                _GIF_FRAME_CACHE._max_pixels = 5_000
                for _ in range(6):
                    gif.get_next_frame()  # forces loop + re-decode + eviction
                self.assertLessEqual(_GIF_FRAME_CACHE._pixels, 5_000)
                self.assertLessEqual(len(_GIF_FRAME_CACHE._cache), 3)
            finally:
                _GIF_FRAME_CACHE._max_pixels = original_max
                _GIF_FRAME_CACHE._cache.clear()
                _GIF_FRAME_CACHE._order.clear()
                _GIF_FRAME_CACHE._pixels = 0
                gif.close()

    def test_cache_survives_key_close(self):
        """Frames must stay usable after a KeyGIF instance is closed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.gif")
            make_gif(path, frames=2)
            gif = KeyGIF(controller_key=FakeControllerKey(), gif_path=path, fps=10, loop=True)
            frame = gif.get_next_frame()
            gif.close()
            self.assertEqual(frame.size, (64, 64))
            self.assertEqual(frame.getpixel((0, 0))[3], 255)


class ContentCompositionTest(unittest.TestCase):
    """Source-over associativity: compositing media over the background must
    equal compositing the same layers over transparent and then over the
    background - the invariant the cached content layer relies on."""

    def _compose(self, layers, base, layouts):
        result = base
        for image, layout_manager in zip(layers, layouts):
            if image is not None:
                composed = layout_manager.add_image_to_background(image=image, background=result)
                result = composed
        return result

    def test_source_over_associative(self):
        background = Image.new("RGBA", (72, 72), (40, 60, 80, 255))
        draw = ImageDraw.Draw(background)
        draw.ellipse((10, 10, 60, 60), fill=(200, 50, 50, 200))

        m1 = Image.new("RGBA", (72, 72), (0, 200, 100, 180))
        draw = ImageDraw.Draw(m1)
        draw.rectangle((5, 5, 40, 40), fill=(30, 30, 200, 220))

        m2 = Image.new("RGBA", (72, 72), (255, 200, 0, 120))
        draw = ImageDraw.Draw(m2)
        draw.polygon([(20, 50), (50, 20), (60, 60)], fill=(255, 255, 255, 200))

        input_key = FakeKeyInput()
        lm1 = LayoutManager(input_key)
        lm2 = LayoutManager(input_key)

        direct = self._compose([m1, m2], background.copy(), [lm1, lm2])

        # Cached-content equivalent: layers over transparent, then over bg.
        transparent = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        content = self._compose([m1, m2], transparent, [lm1, lm2])
        cached = background.copy()
        cached.alpha_composite(content)

        # Compositing order changes the 8-bit rounding, so pixels may differ by
        # at most 1/255 - visually identical, and stable across renders (the
        # hash dedup compares against the same path's previous output).
        a = direct.tobytes()
        b = cached.tobytes()
        self.assertEqual(len(a), len(b))
        max_diff = max(abs(x - y) for x, y in zip(a, b))
        self.assertLessEqual(max_diff, 1, f"max channel diff {max_diff}")

    def test_blend_over_transparent_differs_from_direct(self):
        """Blend modes must NOT be cached against a transparent backdrop -
        the cache must be skipped for keys using them."""
        background = Image.new("RGBA", (72, 72), (200, 40, 40, 255))
        source = Image.new("RGBA", (72, 72), (40, 40, 200, 255))

        direct = blend(background, source, "difference")
        transparent = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        over_transparent = blend(transparent, source, "difference")
        cached = background.copy()
        cached.alpha_composite(over_transparent)

        self.assertNotEqual(list(direct.tobytes()), list(cached.tobytes()),
                            "blend against transparent must differ from blend against bg")


if __name__ == "__main__":
    unittest.main()


class _FakeBgDeck:
    def key_layout(self):
        return (1, 1)

    def key_count(self):
        return 1

    def key_image_format(self):
        return {"size": (72, 72), "format": "JPEG", "rotation": 0, "flip": (False, False)}

    def get_rotation(self):
        return 0

    def get_serial_number(self):
        return "FAKE-BG"


class _FakeBgDeckController:
    """Enough of a DeckController for BackgroundVideo + Background."""

    def __init__(self):
        self.deck = _FakeBgDeck()
        self.key_spacing = (36, 36)
        self.active_page = None

    def get_key_image_size(self):
        return (72, 72)

    def generate_alpha_key(self):
        return Image.new("RGBA", (72, 72), (0, 0, 0, 0))


class BackgroundPacingTest(unittest.TestCase):
    """The background video must pace itself in real time: advance only when
    the current frame's delay elapsed, and return None (no change) otherwise,
    so keys can skip re-rendering."""

    def _make_video(self, path, fps=None):
        fake_dc = _FakeBgDeckController()
        video = BackgroundVideo(fake_dc, path, loop=True, fps=fps, opacity=1.0)
        # Shut the cache's background thread down quietly.
        video._closed = True
        return video

    def test_native_gif_delay_pacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bg.gif")
            make_gif(path, frames=4)  # duration=40ms per frame

            video = self._make_video(path)
            self.assertIsNone(video.fps)  # native pacing
            self.assertEqual(video._gif_delays, [40, 40, 40, 40])

            tiles = video.get_next_tiles()
            self.assertIsNotNone(tiles)  # first call shows frame 0
            self.assertEqual(video.active_frame, 0)

            # Immediately: same frame still on screen -> no change.
            self.assertIsNone(video.get_next_tiles())

            time.sleep(0.05)
            tiles = video.get_next_tiles()
            self.assertIsNotNone(tiles)  # 50ms >= 40ms delay -> advanced
            self.assertEqual(video.active_frame, 1)

            video.close()

    def test_explicit_fps_pacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bg.gif")
            make_gif(path, frames=4)

            video = self._make_video(path, fps=10)  # 100ms per frame
            self.assertEqual(video._current_frame_delay(), 0.1)
            video.get_next_tiles()
            time.sleep(0.06)  # < 100ms -> still frame 0
            self.assertIsNone(video.get_next_tiles())
            time.sleep(0.05)  # total 110ms >= 100ms -> advanced
            self.assertIsNotNone(video.get_next_tiles())
            self.assertEqual(video.active_frame, 1)

            video.close()

    def test_loop_wraps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bg.gif")
            make_gif(path, frames=3)  # 40ms delays

            video = self._make_video(path)
            video.active_frame = 2
            video._last_frame_time = None  # force "first" path -> frame 0 shown
            tiles = video.get_next_tiles()
            self.assertIsNotNone(tiles)
            self.assertEqual(video.active_frame, 0)

            video.close()


class _FakeBackground:
    """Minimal stand-in so Background.update_tiles can be exercised."""

    def __init__(self, video):
        self.video = video
        self.frame_counter = 0


class BackgroundFrameCounterTest(unittest.TestCase):
    def test_update_tiles_bumps_counter_only_on_change(self):
        from src.backend.DeckManagement.DeckController import Background

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bg.gif")
            make_gif(path, frames=4)

            fake_dc = _FakeBgDeckController()
            video = BackgroundVideo(fake_dc, path, loop=True, fps=None, opacity=1.0)
            video._closed = True
            bg = Background(fake_dc)
            bg.video = video

            # First update: tiles swap, counter bumps.
            old = bg.frame_counter
            bg.update_tiles()
            self.assertEqual(bg.frame_counter, old + 1)

            # Immediately: no frame advance -> no swap, no bump.
            old = bg.frame_counter
            bg.update_tiles()
            self.assertEqual(bg.frame_counter, old)

            time.sleep(0.05)
            bg.update_tiles()
            self.assertEqual(bg.frame_counter, old + 1)

            video.close()


class AssetRenderLayerTest(unittest.TestCase):
    """Assets return their layer pre-resized to the layout size, cached so the
    resize happens once (per layout for static images, per frame for GIFs)."""

    def test_input_image_layer_cached_per_layout(self):
        from src.backend.DeckManagement.Subclasses.KeyImage import InputImage

        fake = FakeKeyInput()
        img = InputImage(fake, Image.new("RGBA", (192, 192), (10, 20, 30, 255)))
        lm = LayoutManager(fake)
        lm.set_action_layout(ImageLayout(size=1.0, fill_mode="cover"), update=False)

        a = img.get_render_layer(lm, (72, 72))
        b = img.get_render_layer(lm, (72, 72))
        self.assertIs(a, b, "same layout must reuse the cached resize")
        self.assertEqual(a.size, (72, 72))

        # Different layout size -> different cached layer.
        lm.set_action_layout(ImageLayout(size=1.5, fill_mode="cover"), update=False)
        c = img.get_render_layer(lm, (72, 72))
        self.assertIsNot(a, c)
        self.assertEqual(c.size, (108, 108))
        img.close()

    def test_keygif_render_layer_cached_across_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "g.gif")
            make_gif(path, frames=3)
            gif = KeyGIF(controller_key=FakeControllerKey(), gif_path=path, fps=10)
            fake = FakeKeyInput()
            lm = LayoutManager(fake)
            lm.set_action_layout(ImageLayout(size=1.0, fill_mode="cover"), update=False)

            first = gif.get_render_layer(lm, (72, 72))  # frame 0 -> decode + resize
            self.assertEqual(first.size, (72, 72))
            gif.get_render_layer(lm, (72, 72))  # frame 1
            gif.get_render_layer(lm, (72, 72))  # frame 2
            wrapped = gif.get_render_layer(lm, (72, 72))  # loops back to frame 0
            self.assertIs(wrapped, first, "frame 0's resize must be reused after the loop")
            gif.close()

    def test_pre_resized_matches_plain_composition(self):
        from src.backend.DeckManagement.Subclasses.KeyImage import InputImage

        fake = FakeKeyInput()
        img = InputImage(fake, Image.new("RGBA", (192, 192), (10, 20, 30, 255)))
        lm = LayoutManager(fake)
        lm.set_action_layout(ImageLayout(size=1.0, fill_mode="cover"), update=False)
        bg = Image.new("RGBA", (72, 72), (200, 100, 50, 255))

        plain = lm.add_image_to_background(image=img.get_raw_image(), background=bg.copy())
        layer = img.get_render_layer(lm, (72, 72))
        pre = lm.add_image_to_background(image=layer, background=bg.copy(), pre_resized=True)

        self.assertEqual(list(plain.tobytes()), list(pre.tobytes()))
        img.close()
