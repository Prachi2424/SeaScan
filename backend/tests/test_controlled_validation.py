import json

from app.validation.controlled import attribution_metrics, evaluate


def test_misses_are_included_and_absent_cases_are_separate():
    metrics = attribution_metrics([
        {'source_present': True, 'source_rank': 1, 'candidate_count': 2},
        {'source_present': True, 'source_rank': None, 'candidate_count': 1},
        {'source_present': False, 'source_rank': None, 'candidate_count': 1},
    ])
    assert metrics['top_1_accuracy'] == .5
    assert metrics['top_3_accuracy'] == .5
    assert metrics['mean_reciprocal_rank'] == .5
    assert metrics['source_absent_cases_with_candidates'] == 1


def test_controlled_benchmark_records_successes_and_known_limits(tmp_path):
    report = evaluate(tmp_path)
    assert report['drift']['hindcast_position_error_km'] < .001
    assert report['drift']['forecast_position_error_km'] < .001
    assert report['drift']['origin_time_error'] is None
    assert report['sparse_environment_rejected']
    cases = {case['name']: case for case in report['cases']}
    assert cases['clear_source']['source_rank'] == 1
    assert cases['source_AIS_gap']['source_rank'] is None
    assert cases['source_absent_nearby_traffic']['candidate_count'] > 0
    assert cases['source_absent_distant_traffic']['candidate_count'] == 0
    assert json.loads((tmp_path / 'controlled-validation.json').read_text()) == report
    assert evaluate(tmp_path) == report
