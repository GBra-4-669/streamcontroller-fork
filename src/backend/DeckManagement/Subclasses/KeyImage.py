"""
Author: Core447
Year: 2024

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This programm comes with ABSOLUTELY NO WARRANTY!

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
from src.backend.DeckManagement.Subclasses.SingleKeyAsset import SingleKeyAsset
from PIL import Image, ImageOps

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.backend.DeckManagement.DeckController import ControllerInput, LayoutManager

class InputImage(SingleKeyAsset):
    def __init__(self, controller_input: "ControllerInput", image: Image.Image):
        """
        Initialize the class with the given controller key, image, fill mode, size, vertical alignment, and horizontal alignment.

        Parameters:
            controller_key (ControllerKey): The key of the controller.
            image (Image.Image): The image to be displayed.
            fill_mode (str, optional): The mode for filling the image. Defaults to "cover".
            size (float, optional): The size of the image. Defaults to 1.
            valign (float, optional): The vertical alignment of the image. Defaults to 0. Ranges from -1 to 1.
            halign (float, optional): The horizontal alignment of the image. Defaults to 0. Ranges from -1 to 1.
        """
        super().__init__(controller_input)
        self.image = image.convert("RGBA")

        if self.image is None:
            self.image = self.controller_input.get_empty_background()

        # Resize cache: this asset's image is immutable, so the per-layout
        # resize (cover/contain/stretch at the composed layout size) is a
        # constant - compute it once per (target size, fill mode) instead of on
        # every render.
        self._render_layer_cache: dict[tuple, Image.Image] = {}

    def get_raw_image(self) -> Image.Image:
        if not hasattr(self, "image"):
            return
        return self.image

    def get_render_layer(self, layout_manager: "LayoutManager", background_size: tuple[int, int]) -> Image.Image | None:
        layout = layout_manager.get_composed_layout()
        image_size = (int(background_size[0] * layout.size), int(background_size[1] * layout.size))
        if 0 in image_size:
            return None

        cache_key = (image_size, layout.fill_mode)
        cached = self._render_layer_cache.get(cache_key)
        if cached is not None:
            return cached

        if layout.fill_mode == "stretch":
            resized = self.image.resize(image_size, Image.Resampling.BILINEAR)
        elif layout.fill_mode == "cover":
            resized = ImageOps.cover(self.image, image_size, Image.Resampling.BILINEAR)
        else:
            resized = ImageOps.contain(self.image, image_size, Image.Resampling.BILINEAR)
        self._render_layer_cache[cache_key] = resized
        return resized

    def close(self) -> None:
        if not hasattr(self, "image"):
            # Already closed
            return
        # Drop the cached render layers WITHOUT closing them: the media thread
        # may still be compositing one of them (set_image/clear run without the
        # render lock), and PIL's close() frees the backing buffer out from
        # under it - an in-flight blend then crashes with "Operation on closed
        # image" and kills the media thread. Refcount/GC reclaims the images
        # once no renderer references them anymore.
        self._render_layer_cache.clear()
        self.image.close()
        self.image = None
        del self.image
        return
