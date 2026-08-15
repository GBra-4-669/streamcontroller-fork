"""Unit tests for src.backend.DeckManagement.blend_modes.

Known-value checks use opaque backdrops/sources where the W3C formula reduces to
    Co = B(Cb, Cs),  ao = 1
so expected colors are hand-computable. Tolerance handles float32 rounding.
"""
import unittest

from PIL import Image

from src.backend.DeckManagement.blend_modes import BLEND_MODES, blend


def rgba(rgb, a=255):
    return Image.new("RGBA", (1, 1), (*rgb, a))


class BlendModesTest(unittest.TestCase):
    def assertPixelAlmostEqual(self, actual, expected, tol=2):
        self.assertEqual(len(actual), len(expected), f"length mismatch {actual}")
        for a, e in zip(actual, expected):
            self.assertTrue(abs(a - e) <= tol, f"pixel {actual} != {expected} (tol {tol})")

    def test_multiply_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255)), "multiply")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (0, 0, 0, 255))

    def test_screen_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255)), "screen")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (255, 0, 255, 255))

    def test_darken_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255)), "darken")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (0, 0, 0, 255))

    def test_lighten_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255)), "lighten")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (255, 0, 255, 255))

    def test_difference_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 255, 0)), "difference")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (255, 255, 0, 255))

    def test_exclusion_opaque(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 255, 0)), "exclusion")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (255, 255, 0, 255))

    def test_color_dodge_gray_on_gray_is_white(self):
        out = blend(rgba((128, 128, 128)), rgba((128, 128, 128)), "color-dodge")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (255, 255, 255, 255), tol=3)

    def test_color_burn_gray_on_gray_is_black(self):
        out = blend(rgba((128, 128, 128)), rgba((128, 128, 128)), "color-burn")
        self.assertPixelAlmostEqual(out.getpixel((0, 0)), (0, 0, 0, 255), tol=3)

    def test_normal_matches_alpha_composite(self):
        bg = Image.new("RGBA", (6, 6), (255, 0, 0, 255))
        src = Image.new("RGBA", (6, 6), (0, 0, 255, 128))
        a = blend(bg, src, "normal")
        b = bg.copy()
        b.alpha_composite(src)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_semitransparent_over_opaque_preserves_alpha(self):
        # Regression guard: the old paste(..., mask=image) corrupted the
        # destination alpha to 191; correct compositing keeps it opaque (~255).
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255), 128), "multiply")
        self.assertGreaterEqual(out.getpixel((0, 0))[3], 254)

    def test_fully_transparent_source_is_noop(self):
        out = blend(rgba((255, 0, 0)), rgba((0, 0, 255), 0), "multiply")
        self.assertEqual(out.getpixel((0, 0)), (255, 0, 0, 255))

    def test_unknown_mode_falls_back_to_source_over(self):
        bg = rgba((255, 0, 0))
        src = rgba((0, 0, 255), 128)
        a = blend(bg, src, "bogus-mode")
        b = blend(bg, src, "normal")
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_all_modes_return_rgba_same_size(self):
        bg = Image.new("RGBA", (8, 8), (120, 60, 30, 200))
        src = Image.new("RGBA", (8, 8), (30, 200, 90, 160))
        self.assertEqual(set(BLEND_MODES), {
            "normal", "multiply", "screen", "darken", "lighten", "hard-light",
            "overlay", "color-dodge", "color-burn", "difference", "exclusion",
            "soft-light",
        })
        for mode in BLEND_MODES:
            out = blend(bg, src, mode)
            self.assertEqual(out.mode, "RGBA", mode)
            self.assertEqual(out.size, (8, 8), mode)


if __name__ == "__main__":
    unittest.main()
