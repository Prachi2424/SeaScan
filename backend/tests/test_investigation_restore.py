"""Regression coverage for loading saved case results without rerunning analysis."""
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.services.investigations import record_analysis


def test_case_details_restore_latest_results_and_keep_cases_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('SEASCAN_DATABASE_URL', f'sqlite:///{tmp_path}/restore.db')
    monkeypatch.setenv('SEASCAN_UPLOAD_DIRECTORY', str(tmp_path / 'uploads'))
    monkeypatch.setenv('SEASCAN_PROCESSED_DIRECTORY', str(tmp_path / 'processed'))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            first = client.post('/api/investigations', json={'title': 'Saved case'}).json()['id']
            other = client.post('/api/investigations', json={'title': 'Empty case'}).json()['id']
            import sqlite3
            with sqlite3.connect(tmp_path / 'restore.db') as connection:
                connection.row_factory = sqlite3.Row
                record_analysis(connection, first, 'attribution', {'candidate_count': 1})
                record_analysis(connection, first, 'attribution', {'candidate_count': 2})
                record_analysis(connection, first, 'drift_backward', {'seed': {'duration_hours': 24}})
        with TestClient(app) as client:
            restored = client.get(f'/api/investigations/{first}').json()
            assert restored['analyses']['attribution']['candidate_count'] == 2
            assert restored['analyses']['drift_backward']['seed']['duration_hours'] == 24
            assert client.get(f'/api/investigations/{other}').json()['analyses'] == {}
            assert client.get('/api/investigations/missing-case').status_code == 404
    finally:
        get_settings.cache_clear()
