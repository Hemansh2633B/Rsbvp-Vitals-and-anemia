import numpy as np
import cv2
from rppg_core.pipeline import keep_roi_inside_frame, mean_rgb_from_roi, get_multi_rois


def test_roi_clamping_and_named_regions():
    shape = (100, 120, 3)
    assert keep_roi_inside_frame((-5, -7, 30, 40), shape) == (0, 0, 30, 40)
    rois = get_multi_rois((10, 10, 90, 80), shape)
    assert set(rois) == {'forehead', 'left_cheek', 'right_cheek'}
    assert all(x >= 0 and y >= 0 and x+w <= 120 and y+h <= 100 for x,y,w,h in rois.values())


def test_skin_color_mask_does_not_accept_blue_background():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[:] = (220, 50, 20)  # blue-dominant BGR background
    assert mean_rgb_from_roi(frame, (0, 0, 40, 40)) is None
