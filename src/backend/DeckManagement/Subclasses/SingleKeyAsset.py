"""
Author: Core447
Year: 2023

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This programm comes with ABSOLUTELY NO WARRANTY!

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

from PIL import Image, ImageOps, ImageDraw, ImageFont
import os

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.backend.DeckManagement.DeckController import ControllerInput
    from src.backend.DeckManagement.DeckController import LayoutManager

class SingleKeyAsset:
    def __init__(self, controller_input: "ControllerInput"):
        self.controller_input = controller_input
        self.deck_controller = controller_input.deck_controller

    def get_raw_image(self) -> Image.Image:
        return Image.open(os.path.join("Assets", "images", "error.png"))

    def get_render_layer(self, layout_manager: "LayoutManager", background_size: tuple[int, int]) -> Image.Image | None:
        """Return this asset already resized to its layout size for the given
        background, or None to let the caller fall back to the plain path.

        Animated assets advance their frame here (once per render). Callers
        must not mutate or close the returned image - it may be shared/cached.
        The default implementation returns None, keeping the per-render resize
        inside LayoutManager.add_image_to_background().
        """
        return None

    def get_preview_image(self) -> Image.Image | None:
        """Current frame WITHOUT advancing the animation - used for GUI
        previews, so a preview render must never desync the deck's playback.
        """
        return self.get_raw_image()

    def close(self):
        pass