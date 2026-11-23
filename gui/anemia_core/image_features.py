"""Conservative image QA and colour summaries for research curation only.

Nothing in this module estimates, predicts or suggests hemoglobin, iron or
anemia. It answers one question only: is an image (or a researcher-verified
mask ROI) usable for downstream *research curation*, and what does it look
like colour-wise? All thresholds are documented research heuristics (2026-11),
not calibrated clinical cut-offs. Real-world validity of any feature derived
here requires a governed, independently evaluated study — see
docs/ANEMIA_MODEL_CARD.md.

Sensitivity disclaimer: RGB/HSV/CIELAB values are strongly affected by camera
auto-white-balance, exposure, illumination spectrum/geometry, lens vignetting
and JPEG quantification. Cross-device or cross-session comparisons without
controlled capture are uninterpretable.
"""
from __future__ import annotations
import math
import cv2
import numpy as np

DEFAULT_MIN_BRIGHTNESS = 40.0        # mean gray below this => low_illumination
DEFAULT_MAX_BRIGHTNESS = 235.0       # mean gray above this => overexposed
DEFAULT_MAX_CLIP_FRACTION = 0.35     # aggregated rail-saturated channel pixels
DEFAULT_MIN_SHARPNESS = 8.0          # Laplacian variance floor
DEFAULT_MOTION_BLUR_ANISO = 0.5      # |var(Gx)-var(Gy)|/(var(Gx)+var(Gy))
DEFAULT_MOTION_BLUR_MAX_SHARPNESS = 20.0
DEFAULT_MAX_UNDEREXPOSED = 0.50      # fraction of near-black pixels
DEFAULT_MAX_OVEREXPOSED = 0.50       # fraction of near-white pixels
HIST_BINS = 16


def _gradient_anisotropy(gray):
    g = gray.astype(np.float64)
    gx = cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_64F, 0, 1, ksize=3)
    vx, vy = float(gx.var()), float(gy.var())
    return abs(vx - vy) / (vx + vy + 1e-12)


def assess_image(image, *, min_width=160, min_height=120,
                 min_brightness=DEFAULT_MIN_BRIGHTNESS,
                 max_brightness=DEFAULT_MAX_BRIGHTNESS,
                 max_clip_fraction=DEFAULT_MAX_CLIP_FRACTION,
                 min_sharpness=DEFAULT_MIN_SHARPNESS,
                 motion_blur_aniso=DEFAULT_MOTION_BLUR_ANISO,
                 motion_blur_max_sharpness=DEFAULT_MOTION_BLUR_MAX_SHARPNESS):
    """Decode/quality gate. Returns a dict with both a human-readable `reason`
    (first failing check) and a machine-readable `reasons` list."""
    if image is None or not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        return {"usable": False, "reason": "image_unreadable", "reasons": ["image_unreadable"]}
    h, w = image.shape[:2]
    if h < min_height or w < min_width:
        return {"usable": False, "reason": "image_too_small", "reasons": ["image_too_small"],
                "width": w, "height": h}
    if image.ndim != 3 or image.shape[2] < 3:
        return {"usable": False, "reason": "expected_color_image", "reasons": ["expected_color_image"],
                "width": w, "height": h}
    if not np.isfinite(image[:, :, :3]).all():
        return {"usable": False, "reason": "non_finite_pixels", "reasons": ["non_finite_pixels"],
                "width": w, "height": h}
    rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float64)
    brightness = float(gray.mean())
    clipped = float(np.mean((rgb <= 2) | (rgb >= 253)))
    under = float(np.mean(gray <= 8.0))
    over = float(np.mean(gray >= 248.0))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    anisotropy = _gradient_anisotropy(gray)

    reasons = []
    if brightness < min_brightness:
        reasons.append("low_illumination")
    if brightness > max_brightness:
        reasons.append("overexposed")
    if under > DEFAULT_MAX_UNDEREXPOSED:
        reasons.append("underexposed")
    if over > DEFAULT_MAX_OVEREXPOSED:
        reasons.append("overexposed")
    if clipped > max_clip_fraction:
        reasons.append("excessive_clipping")
    if sharpness < min_sharpness:
        reasons.append("low_sharpness")
    if anisotropy > motion_blur_aniso and sharpness < motion_blur_max_sharpness:
        # Directional smear with little in-plane detail: possible motion blur.
        # Heuristic only — defocus blur is not separable this way reliably.
        reasons.append("possible_motion_blur")

    return {"usable": not reasons, "reason": reasons[0] if reasons else None,
            "reasons": reasons, "width": w, "height": h,
            "sharpness_laplacian_variance": sharpness,
            "clipped_channel_fraction": clipped,
            "mean_brightness": brightness,
            "underexposed_fraction": under,
            "overexposed_fraction": over,
            "motion_blur_direction_ratio": float(anisotropy)}


def validate_mask(mask, image_shape, *, min_pixels=20, max_coverage_fraction=0.98):
    """Explicit validation of a researcher-supplied binary mask.

    Returns ``{"valid": bool, "reason": str|None, "coverage_fraction": float,
    "n_pixels": int}`` — never raises, so audit pipelines can record the
    rejection reason instead of crashing.
    """
    if mask is None:
        return {"valid": False, "reason": "mask_missing", "coverage_fraction": 0.0, "n_pixels": 0}
    m = np.asarray(mask)
    if m.ndim != 2:
        return {"valid": False, "reason": "mask_not_2d", "coverage_fraction": 0.0, "n_pixels": 0}
    h, w = int(image_shape[0]), int(image_shape[1])
    if m.shape != (h, w):
        return {"valid": False, "reason": "mask_shape_mismatch",
                "coverage_fraction": 0.0, "n_pixels": int(m.size and np.count_nonzero(m))}
    n = int(np.count_nonzero(m))
    coverage = float(n / m.size)
    if n < min_pixels:
        return {"valid": False, "reason": "mask_too_small", "coverage_fraction": coverage, "n_pixels": n}
    if coverage > max_coverage_fraction:
        return {"valid": False, "reason": "mask_covers_full_frame", "coverage_fraction": coverage, "n_pixels": n}
    return {"valid": True, "reason": None, "coverage_fraction": coverage, "n_pixels": n}


def _channel_stats(channel):
    data = channel.astype(np.float64)
    hist, _ = np.histogram(data, bins=HIST_BINS, range=(0, 256))
    total = max(1, int(data.size))
    return {"mean": float(data.mean()), "std": float(data.std()),
            "p5": float(np.percentile(data, 5)), "p25": float(np.percentile(data, 25)),
            "p50": float(np.percentile(data, 50)), "p75": float(np.percentile(data, 75)),
            "p95": float(np.percentile(data, 95)),
            "hist": (hist / total).tolist()}


def color_summary(image, mask=None):
    """Per-channel stats in RGB, HSV and CIELAB; full image unless a 2-D mask
    is supplied. Mask must be the same size as the image and select at least
    20 pixels (see validate_mask). All outputs are finite floats.

    This function never localizes conjunctiva and never estimates hemoglobin.
    """
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("expected a decoded three-channel image")
    if not np.isfinite(image[:, :, :3]).all():
        raise ValueError("image contains non-finite pixel values")
    rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB)
    spaces = {"rgb": rgb,
              "hsv": cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV),
              "lab": cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)}
    selection = {}
    if mask is not None:
        check = validate_mask(mask, rgb.shape[:2])
        if not check["valid"]:
            raise ValueError(f"invalid mask: {check['reason']}")
        m = np.asarray(mask, dtype=bool)
        for name, data in spaces.items():
            selection[name] = data[m]
        coverage = check["coverage_fraction"]
        n_pixels = check["n_pixels"]
    else:
        for name, data in spaces.items():
            selection[name] = data.reshape(-1, 3)
        coverage = 1.0
        n_pixels = int(rgb.shape[0] * rgb.shape[1])

    result = {}
    for name, pixels in selection.items():
        result[name] = {
            "channels": [_channel_stats(pixels[:, i]) for i in range(3)],
            "mean": pixels.mean(axis=0).tolist(),
            "std": pixels.std(axis=0).tolist(),
        }
    luminance = rgb.astype(np.float64).mean(axis=2)
    lum_sel = luminance[m] if mask is not None else luminance.reshape(-1)
    sel_rgb = rgb[m] if mask is not None else rgb.reshape(-1, 3)
    result["_roi"] = {"coverage_fraction": float(coverage), "n_pixels": int(n_pixels)}
    result["_illumination"] = {
        "mean_brightness": float(lum_sel.mean()),
        "clipped_channel_fraction": float(np.mean((sel_rgb <= 2) | (sel_rgb >= 253))),
    }
    for space in result.values():
        if isinstance(space, dict) and "channels" in space:
            for ch in space["channels"]:
                # fail loudly on non-finite output instead of emitting NaN JSON
                assert all(np.isfinite(v) for k, v in ch.items() if k != "hist")
    return result
