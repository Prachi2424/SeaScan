"""Run with: python -m app.validation.controlled --output <directory>."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from pyproj import Geod

from app.ais.attribution import SCORE_WEIGHTS, rank_candidates
from app.drift.advection import simulate_particles

FIELDS = {key: key for key in ['mmsi', 'timestamp', 'latitude', 'longitude', 'speed_knots', 'course_degrees']}
EVENT = '2020-01-01T00:00:00Z'
SOURCE = '111111111'


def track(mmsi, latitude, minutes=(-10, 10)):
    return [[mmsi, (pd.Timestamp(EVENT) + pd.Timedelta(minutes=t)).isoformat(), latitude, t * .001, 4, 90] for t in minutes]


def attribution_metrics(cases):
    positives = [case for case in cases if case['source_present']]
    ranks = [case['source_rank'] for case in positives]
    recovered = [rank for rank in ranks if rank is not None]
    return {
        'source_present_cases': len(positives),
        'top_1_accuracy': sum(rank == 1 for rank in ranks) / len(ranks) if ranks else None,
        'top_3_accuracy': sum(rank is not None and rank <= 3 for rank in ranks) / len(ranks) if ranks else None,
        'source_recall': len(recovered) / len(ranks) if ranks else None,
        'mean_rank_when_retrieved': sum(recovered) / len(recovered) if recovered else None,
        'mean_reciprocal_rank': sum(1 / rank if rank else 0 for rank in ranks) / len(ranks) if ranks else None,
        'source_absent_cases_with_candidates': sum(not case['source_present'] and case['candidate_count'] > 0 for case in cases),
    }


def evaluate(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    geod = Geod(ellps='WGS84')
    # Independent analytic reference: 1 m/s due east for 1 hour at the equator.
    observed_lon, observed_lat, _ = geod.fwd(0, 0, 90, 3600)
    environment = pd.DataFrame([
        [pd.Timestamp(EVENT) + pd.Timedelta(hours=h), lat, lon, 1, 0, 0, 0]
        for h in range(3) for lat, lon in [(-.1, -.1), (-.1, .1), (.1, -.1), (.1, .1)]
    ], columns=['timestamp', 'latitude', 'longitude', 'current_u', 'current_v', 'wind_u', 'wind_v'])
    parameters = dict(observed_at='2020-01-01T01:00:00Z', duration_hours=1, step_minutes=15,
                      particle_count=20, initial_spread_meters=0, windage_factor=0, random_seed=42)
    drift_metrics = {}
    for name, direction, expected_lon in [('hindcast', -1, 0), ('forecast', 1, geod.fwd(0, 0, 90, 7200)[0])]:
        result = simulate_particles(environment, latitude=observed_lat, longitude=observed_lon, direction=direction, **parameters)
        final = result['trajectory']['features'][-1]
        lon, lat = final['geometry']['coordinates']
        drift_metrics[name + '_position_error_km'] = abs(geod.inv(expected_lon, 0, lon, lat)[2]) / 1000
    drift_metrics['origin_time_error'] = None  # Duration is supplied, not inferred.
    drift_metrics['origin_time_note'] = 'Release duration supplied as ground truth; age estimation is not evaluated.'
    sparse = environment.iloc[:4].copy()
    try:
        simulate_particles(sparse, latitude=0, longitude=0, direction=1, **{**parameters, 'observed_at': '2020-01-02T00:00:00Z'})
        sparse_rejected = False
    except HTTPException as error:
        if error.status_code != 422:
            raise
        sparse_rejected = True

    scenarios = [
        ('clear_source', True, track(SOURCE, 0) + track('222222222', .02)),
        ('crowded_tracks', True, track(SOURCE, 0) + track('222222222', .005) + track('333333333', .01)),
        ('wrong_time_distractor', True, track(SOURCE, 0) + track('222222222', 0, (120, 140))),
        ('source_AIS_gap', True, track(SOURCE, 0, (-120, 120)) + track('222222222', .01)),
        ('source_absent_nearby_traffic', False, track('222222222', .005)),
        ('source_absent_distant_traffic', False, track('222222222', 1)),
    ]
    cases = []
    with tempfile.TemporaryDirectory() as directory:
        for name, present, rows in scenarios:
            path = Path(directory) / 'tracks.csv'
            pd.DataFrame(rows, columns=list(FIELDS)).to_csv(path, index=False)
            excluded = []
            candidates = rank_candidates(path, {'field_mapping': FIELDS}, origin_latitude=0, origin_longitude=0,
                                         estimated_origin_at=EVENT, search_radius_km=5, temporal_window_minutes=15,
                                         behavior_window_hours=24, release_heading=90, exclusions=excluded)
            order = [candidate['mmsi'] for candidate in candidates]
            cases.append(dict(name=name, source_present=present, source_rank=order.index(SOURCE) + 1 if SOURCE in order else None,
                              candidate_count=len(order), candidate_order=order, excluded=excluded))
    code_hashes = {}
    for relative in ['ais/attribution.py', 'drift/advection.py', 'validation/controlled.py']:
        code_hashes[relative] = hashlib.sha256((Path(__file__).parents[1] / relative).read_bytes()).hexdigest()
    report = dict(benchmark_version='1.0', evidence_kind='synthetic', seed=42, python=platform.python_version(),
                  code_sha256=code_hashes, score_weights=SCORE_WEIGHTS, drift=drift_metrics,
                  sparse_environment_rejected=sparse_rejected, attribution=attribution_metrics(cases), cases=cases,
                  limitations=['Small hand-designed fixtures are regression checks, not real-world accuracy estimates.',
                               'No segmentation, release-age estimation, coastline, weathering or spoofing evaluation.',
                               'Nearby traffic can still be ranked when the true source is absent; scores do not identify guilt.',
                               'Zero spread and constant current test numerical transport only, not ocean uncertainty.'])
    (output / 'controlled-validation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    metrics = report['attribution']
    lines = ['# SeaScan controlled validation', '', '**Synthetic regression benchmark — not operational accuracy.**', '',
             f"Hindcast position error: {drift_metrics['hindcast_position_error_km']:.8f} km.",
             f"Forecast position error: {drift_metrics['forecast_position_error_km']:.8f} km.",
             f'Sparse environmental data rejected: {sparse_rejected}.', '',
             f"Top-1: {metrics['top_1_accuracy']:.0%}; Top-3: {metrics['top_3_accuracy']:.0%} across {metrics['source_present_cases']} source-present cases (missing source tracks count as misses).",
             f"Mean rank when retrieved: {metrics['mean_rank_when_retrieved']}; mean reciprocal rank: {metrics['mean_reciprocal_rank']:.2f}.", '',
             '| Scenario | True source present | Source rank | Candidates |', '|---|---|---|---|']
    lines += [f"| {case['name']} | {case['source_present']} | {case['source_rank'] or 'Not retrieved'} | {case['candidate_count']} |" for case in cases]
    lines += ['', '## Limits', ''] + ['- ' + note for note in report['limitations']]
    lines += ['', 'Origin-time error is not reported because the duration was supplied rather than estimated.',
              'The JSON records per-case exclusions, score weights and source-code hashes for reproducibility.']
    (output / 'controlled-validation.md').write_text('\n'.join(lines) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.output)
    print(json.dumps({'output': str(args.output), 'attribution': report['attribution']}, indent=2))
