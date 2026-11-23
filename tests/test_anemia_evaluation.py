import numpy as np
import pytest
from anemia_core.evaluation import grouped_holdout, regression_metrics


def test_grouped_holdout_never_splits_patient_records():
    ids = ['a','a','b','b','c','c','d','d']
    train, test = grouped_holdout(ids, .25, seed=7)
    assert not set(np.array(ids)[train]) & set(np.array(ids)[test])
    assert len(train) + len(test) == len(ids)


def test_grouped_holdout_requires_ids():
    with pytest.raises(ValueError):
        grouped_holdout(['a', '', 'b'])


def test_regression_metric_values_are_computed_not_stubbed():
    m = regression_metrics([10, 20, 30], [11, 19, 30])
    assert m['mae'] == pytest.approx(2/3)
    assert m['bias'] == pytest.approx(0)
    assert m['loa_lower_95'] < 0 < m['loa_upper_95']
