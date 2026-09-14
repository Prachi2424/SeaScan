from pathlib import Path

from fastapi.testclient import TestClient

from app.ais.validation import validate_ais_file
from app.geospatial.environment import validate_environment_file
from app.main import app


def test_health_check_returns_service_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "seascan-api"


def test_system_config_advertises_real_data_formats() -> None:
    with TestClient(app) as client:
        response = client.get("/api/system/config")

    assert response.status_code == 200
    assert ".tiff" in response.json()["accepted_satellite_formats"]
    assert ".parquet" in response.json()["accepted_ais_formats"]


def test_investigation_is_persisted_and_retrievable() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/api/investigations",
            json={"title": "Arabian Sea slick", "description": "Real-data evidence review."},
        )
        assert create_response.status_code == 201
        investigation_id = create_response.json()["id"]
        read_response = client.get(f"/api/investigations/{investigation_id}")

    assert read_response.status_code == 200
    assert read_response.json()["title"] == "Arabian Sea slick"
    assert read_response.json()["assets"] == []


def test_satellite_upload_refuses_untrained_inference() -> None:
    with TestClient(app) as client:
        investigation = client.post("/api/investigations", json={"title": "No model case"}).json()
        response = client.post(
            "/api/satellite/upload",
            data={"investigation_id": investigation["id"]},
            files={"file": ("scene.png", b"not-an-image", "image/png")},
        )

    assert response.status_code == 503
    assert "will not fabricate" in response.json()["detail"]


FIXTURES = Path(__file__).parent / "fixtures"


def test_ais_validator_extracts_real_column_mapping() -> None:
    result = validate_ais_file(FIXTURES / "ais.csv")

    assert result["valid_position_count"] == 1
    assert result["field_mapping"]["timestamp"] == "BaseDateTime"


def test_environment_validator_requires_velocity_components() -> None:
    result = validate_environment_file(FIXTURES / "currents.csv")

    assert result["velocity_field_mapping"] == {"current_u": "current_u", "current_v": "current_v"}


def test_drift_and_attribution_run_from_persisted_real_format_assets() -> None:
    with TestClient(app) as client:
        investigation = client.post("/api/investigations", json={"title": "Forensics integration case"}).json()
        environment = client.post(
            "/api/environment/upload",
            data={"investigation_id": investigation["id"]},
            files={"file": ("currents.csv", (FIXTURES / "currents.csv").read_bytes(), "text/csv")},
        )
        ais = client.post(
            "/api/ais/upload",
            data={"investigation_id": investigation["id"]},
            files={"file": ("ais.csv", (FIXTURES / "ais.csv").read_bytes(), "text/csv")},
        )
        assert environment.status_code == 201
        assert ais.status_code == 201
        drift = client.post(
            "/api/drift/backward",
            json={
                "environmental_asset_id": environment.json()["asset"]["id"],
                "latitude": 19.0,
                "longitude": 72.0,
                "observed_at": "2026-09-13T10:00:00Z",
                "duration_hours": 0.5,
                "particle_count": 20,
            },
        )
        ranking = client.post(
            "/api/attribution/rank",
            json={
                "ais_asset_id": ais.json()["asset"]["id"],
                "origin_latitude": 19.076,
                "origin_longitude": 72.8777,
                "estimated_origin_at": "2026-09-13T10:00:00Z",
                "search_radius_km": 5,
            },
        )

    assert drift.status_code == 200
    assert drift.json()["direction"] == "backward"
    assert ranking.status_code == 200
    assert ranking.json()["candidates"][0]["mmsi"] == "123456789"
    assert sum(ranking.json()["scoring_formula"].values()) == 1.0
