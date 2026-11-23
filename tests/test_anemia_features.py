import numpy as np
import pytest
import cv2
from anemia_core.image_features import assess_image, color_summary


def test_quality_rejects_small_and_accepts_clear_fixture():
    assert assess_image(np.zeros((50, 50, 3), dtype=np.uint8))['reason'] == 'image_too_small'
    yy, xx = np.indices((200, 240))
    texture = ((xx * 7 + yy * 11) % 180 + 35).astype(np.uint8)
    image = np.repeat(texture[:, :, None], 3, axis=2)
    assert assess_image(image)['usable']


def test_color_features_and_invalid_roi_mask():
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    features = color_summary(image)
    assert set(features) == {'rgb', 'hsv', 'lab'}
    with pytest.raises(ValueError):
        color_summary(image, np.zeros((20, 20), dtype=bool))
