import importlib.util
from pathlib import Path
import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('evaluation', Path(__file__).resolve().parents[2] / 'training/evaluate.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_confusion_counts_and_rates():
    result = evaluation.metrics([1,1,0,0], [1,0,1,0])
    assert [result[key] for key in ('tp','fp','fn','tn')] == [1,1,1,1]
    assert result['dice'] == .5
    assert result['iou'] == pytest.approx(1/3)
    assert result['false_positive_rate'] == .5


def test_empty_truth_is_not_reported_as_perfect_segmentation():
    result = evaluation.metrics(np.zeros(4), np.zeros(4))
    assert result['dice'] is None
    assert result['recall'] is None
    assert result['false_positive_rate'] == 0
    assert evaluation.metrics(np.ones(4), np.zeros(4))['false_positive_rate'] == 1


def test_dimensions_must_match():
    with pytest.raises(ValueError, match='shapes'):
        evaluation.metrics(np.zeros((2,2)), np.zeros(4))
