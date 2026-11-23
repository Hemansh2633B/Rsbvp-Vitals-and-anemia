"""Conservative image QA and colour summaries for research curation only."""
from __future__ import annotations
import cv2
import numpy as np


def assess_image(image, *, min_width=160, min_height=120):
    if image is None or not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        return {"usable": False, "reason": "image_unreadable"}
    h, w = image.shape[:2]
    if h < min_height or w < min_width:
        return {"usable": False, "reason": "image_too_small", "width": w, "height": h}
    if image.ndim != 3 or image.shape[2] < 3:
        return {"usable": False, "reason": "expected_color_image", "width": w, "height": h}
    rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    clipped = float(np.mean((rgb <= 2) | (rgb >= 253)))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    reason = "excessive_clipping" if clipped > .35 else ("low_sharpness" if sharpness < 8 else None)
    return {"usable": reason is None, "reason": reason, "width": w, "height": h,
            "sharpness_laplacian_variance": sharpness, "clipped_channel_fraction": clipped}


def color_summary(image, mask=None):
    """Per-channel mean/std in RGB, HSV, Lab; uses full image unless ROI mask supplied.

    ROI selection must be independently verified; this function does not localize conjunctiva.
    """
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("expected a decoded three-channel image")
    rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB)
    if mask is not None:
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != rgb.shape[:2] or not mask.any():
            raise ValueError("mask must match image and select at least one pixel")
        pixels = rgb[mask]
    else:
        pixels = rgb.reshape(-1, 3)
    result = {}
    for name, data in (("rgb", pixels),
                       ("hsv", cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[mask] if mask is not None else cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).reshape(-1,3)),
                       ("lab", cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[mask] if mask is not None else cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(-1,3))):
        result[name] = {"mean": data.mean(axis=0).tolist(), "std": data.std(axis=0).tolist()}
    return result
