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
    assert {'rgb', 'hsv', 'lab'} <= set(features)
    with pytest.raises(ValueError):
        color_summary(image, np.zeros((20, 20), dtype=bool))


def test_quality_flags_low_illumination_and_blur():
    dark = np.full((200, 240, 3), 5, dtype=np.uint8)
    assert 'low_illumination' in assess_image(dark)['reasons']
    noisy = np.random.default_rng(1).integers(0, 255, (220, 260, 3), dtype=np.uint8)
    blurred = cv2.GaussianBlur(cv2.GaussianBlur(noisy, (11, 11), 0), (31, 1), 0)
    result = assess_image(blurred)
    assert not result['usable']
    assert 'possible_motion_blur' in result['reasons']


def test_quality_rejects_non_finite_pixels():
    image = np.full((200, 240, 3), np.nan)
    assert assess_image(image)['reason'] == 'non_finite_pixels'


def test_validate_mask_reasons_and_coverage():
    from anemia_core.image_features import validate_mask
    image_shape = (200, 240, 3)
    assert validate_mask(None, image_shape)['reason'] == 'mask_missing'
    assert validate_mask(np.zeros((100, 100), bool), image_shape)['reason'] == 'mask_shape_mismatch'
    assert validate_mask(np.zeros((200, 240), bool), image_shape)['reason'] == 'mask_too_small'
    assert validate_mask(np.ones((200, 240), bool), image_shape)['reason'] == 'mask_covers_full_frame'
    ok = np.zeros((200, 240), bool); ok[50:150, 60:180] = True
    result = validate_mask(ok, image_shape)
    assert result['valid'] and result['coverage_fraction'] == pytest.approx(0.25) and result['n_pixels'] == 12000


def test_color_summary_percentiles_hist_and_roi_accounting():
    yy, xx = np.indices((120, 160))
    image = np.stack([np.full_like(xx, 120), np.full_like(xx, 60), np.full_like(xx, 30)], axis=-1).astype(np.uint8)
    mask = np.zeros((120, 160), bool); mask[20:100, 20:140] = True
    result = color_summary(image, mask)
    assert result['_roi']['n_pixels'] == 80 * 120
    assert result['_roi']['coverage_fraction'] == pytest.approx(80 * 120 / (120 * 160))
    for space in ('rgb', 'hsv', 'lab'):
        for ch in result[space]['channels']:
            assert ch['p5'] <= ch['p50'] <= ch['p95']
            assert len(ch['hist']) == 16 and abs(sum(ch['hist']) - 1.0) < 1e-9
            assert np.isfinite(ch['mean']) and np.isfinite(ch['std'])


def test_color_summary_rejects_invalid_mask_with_explicit_reason():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match='mask_shape_mismatch'):
        color_summary(image, np.ones((10, 10), bool))


def test_patient_leakage_guard():
    from anemia_core.evaluation import assert_patient_disjoint
    assert assert_patient_disjoint(['p1', 'p2'], ['p3', 'p4']) is True
    with pytest.raises(ValueError, match='patient leakage'):
        assert_patient_disjoint(['p1', 'p2'], ['p2', 'p9'])
