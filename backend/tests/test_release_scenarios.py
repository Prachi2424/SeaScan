import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.schemas.forensics import ReleaseScenarioRequest


def test_durations_are_bounded_and_unique():
    seed = dict(environmental_asset_id='env', latitude=0, longitude=0, observed_at='2020-01-01T12:00:00Z', duration_hours=1)
    for durations in ([], [1]*6, [1,1], [0], [73], [float('nan')]):
        with pytest.raises(ValidationError):
            ReleaseScenarioRequest(drift=seed, ais_asset_id='ais', durations_hours=durations)


def test_scenarios_persist_without_replacing_main_results(tmp_path, monkeypatch):
    monkeypatch.setenv('SEASCAN_DATABASE_URL', f'sqlite:///{tmp_path}/scenarios.db')
    monkeypatch.setenv('SEASCAN_UPLOAD_DIRECTORY', str(tmp_path/'uploads'))
    monkeypatch.setenv('SEASCAN_PROCESSED_DIRECTORY', str(tmp_path/'processed'))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            case = client.post('/api/investigations', json={'title':'Scenario test'}).json()['id']
            other = client.post('/api/investigations', json={'title':'Other case'}).json()['id']
            def upload(kind, body, case_id=case):
                response = client.post(f'/api/{kind}/upload', data={'investigation_id':case_id}, files={'file':('evidence.csv',body,'text/csv')})
                assert response.status_code == 201, response.text
                return response.json()['asset']['id']
            env = upload('environment', 'timestamp,latitude,longitude,current_u,current_v,wind_u,wind_v\n2020-01-01T00:00:00Z,0,0,0,0,0,0\n2020-01-01T01:00:00Z,0,0,0,0,0,0\n')
            ais_csv = 'mmsi,timestamp,latitude,longitude,speed_knots,course_degrees\n111111111,2020-01-01T00:00:00Z,0,0,1,90\n'
            ais = upload('ais', ais_csv)
            drift = dict(environmental_asset_id=env, latitude=0, longitude=0, observed_at='2020-01-01T01:00:00Z', duration_hours=1, particle_count=20, initial_spread_meters=0)
            main = client.post('/api/drift/backward', json=drift).json()
            payload = dict(drift=drift, ais_asset_id=ais, durations_hours=[1,24])
            response = client.post('/api/release-scenarios', json=payload)
            assert response.status_code == 200, response.text
            scenarios = response.json()
            assert scenarios['scenarios'][0]['status'] == 'complete'
            assert scenarios['scenarios'][1]['status'] == 'unavailable'
            detail = client.get(f'/api/investigations/{case}').json()['analyses']
            assert detail['drift_backward'] == main
            assert 'attribution' not in detail
            assert detail['release_scenarios'] == scenarios
            other_ais = upload('ais', ais_csv, other)
            assert client.post('/api/release-scenarios', json={**payload,'ais_asset_id':other_ais}).status_code == 422
        with TestClient(app) as client:
            assert client.get(f'/api/investigations/{case}').json()['analyses']['release_scenarios'] == scenarios
    finally:
        get_settings.cache_clear()
