from __future__ import annotations

from pathlib import Path


def _read_image(path: Path):
    import numpy as np
    from PIL import Image

    if path.suffix.lower() in {".tif", ".tiff"}:
        import rasterio
        with rasterio.open(path) as dataset:
            pixels = dataset.read(list(range(1, min(dataset.count, 3) + 1)), masked=True).filled(np.nan).astype(np.float32)
    else:
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32).transpose(2, 0, 1)
    while pixels.shape[0] < 3:
        pixels = np.concatenate([pixels, pixels[-1:, :, :]], axis=0)
    return _normalise(pixels)


def _read_mask(path: Path):
    import numpy as np
    from PIL import Image

    if path.suffix.lower() in {".tif", ".tiff"}:
        import rasterio
        with rasterio.open(path) as dataset:
            mask = dataset.read(1)
    else:
        with Image.open(path) as image:
            mask = np.asarray(image.convert("L"))
    return (mask > 0).astype(np.float32)


def _normalise(image):
    import numpy as np

    output = np.zeros_like(image, dtype=np.float32)
    for index, band in enumerate(image):
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            raise ValueError("Image contains no finite pixels.")
        lower, upper = np.percentile(finite, (2, 98))
        output[index] = np.clip((np.nan_to_num(band, nan=lower) - lower) / max(upper - lower, 1.0), 0, 1)
    return output


class OilSpillSegmentationDataset:
    """Pairs real satellite scenes and binary masks by matching filename stems."""

    def __init__(self, image_directory: Path, mask_directory: Path, output_size: int = 256) -> None:
        self.image_directory = image_directory
        self.mask_directory = mask_directory
        self.output_size = output_size
        masks = {path.stem: path for path in mask_directory.iterdir() if path.suffix.lower() in {".tif", ".tiff", ".png"}}
        self.pairs = [(path, masks[path.stem]) for path in image_directory.iterdir() if path.suffix.lower() in {".tif", ".tiff", ".png"} and path.stem in masks]
        if not self.pairs:
            raise ValueError("No matching image/mask pairs found. Match scenes and masks by filename stem.")

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int):
        import torch
        import torch.nn.functional as functional

        image_path, mask_path = self.pairs[index]
        image = torch.from_numpy(_read_image(image_path)).unsqueeze(0)
        mask = torch.from_numpy(_read_mask(mask_path)).unsqueeze(0).unsqueeze(0)
        image = functional.interpolate(image, size=(self.output_size, self.output_size), mode="bilinear", align_corners=False).squeeze(0)
        mask = functional.interpolate(mask, size=(self.output_size, self.output_size), mode="nearest").squeeze(0)
        return image, mask
