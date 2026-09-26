from __future__ import annotations

import hashlib
import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.services.reports import LEGAL_NOTICE, calculate_spill_metrics
from app.services.signing import verify_package


def _investigation(client: TestClient) -> str:
    response = client.post("/api/investigations", json={"title": "Phase 6 report case"})
    assert response.status_code == 201
    return response.json()["id"]


def test_forensic_pdf_is_downloadable_and_integrity_header_matches() -> None:
    with TestClient(app) as client:
        response = client.post("/api/reports/forensic.pdf", json={"investigation_id": _investigation(client)})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 10_000
    assert response.headers["x-report-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert "attachment; filename=" in response.headers["content-disposition"]


def test_forensic_package_contains_pdf_manifest_and_mandatory_notice() -> None:
    with TestClient(app) as client:
        investigation_id = _investigation(client)
        response = client.post("/api/reports/package.zip", json={"investigation_id": investigation_id})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        report_name = next(name for name in archive.namelist() if name.endswith(".pdf"))
        report = archive.read(report_name)
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("manifest.sig")
        assert archive.read("public_key.pem").startswith(b"-----BEGIN PUBLIC KEY-----")
        assert archive.read("signing_certificate.pem").startswith(b"-----BEGIN CERTIFICATE-----")
        notice = archive.read("LEGAL_NOTICE.txt").decode()
    assert manifest["investigation_id"] == investigation_id
    assert manifest["report_sha256"] == hashlib.sha256(report).hexdigest()
    assert manifest["report_filename"] == report_name
    assert manifest["signature_algorithm"] == "Ed25519"
    assert manifest["signer_identity"] == "SeaScan automated test signer"
    verified = verify_package(response.content, {manifest["signing_key_id"]})
    assert verified["valid"] is True
    assert verified["trusted"] is True
    assert LEGAL_NOTICE in notice


def test_modified_report_fails_signature_package_verification() -> None:
    with TestClient(app) as client:
        response = client.post("/api/reports/package.zip", json={"investigation_id": _investigation(client)})
    source = zipfile.ZipFile(io.BytesIO(response.content))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as altered:
        for name in source.namelist():
            contents = source.read(name)
            altered.writestr(name, contents + b"changed" if name.endswith(".pdf") else contents)
    result = verify_package(output.getvalue(), None)
    assert result["valid"] is False
    assert "PDF SHA-256 integrity check failed." in result["errors"]


def test_modified_manifest_fails_signature_verification() -> None:
    with TestClient(app) as client:
        response = client.post("/api/reports/package.zip", json={"investigation_id": _investigation(client)})
    source = zipfile.ZipFile(io.BytesIO(response.content))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as altered:
        for name in source.namelist():
            contents = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(contents)
                manifest["signer_identity"] = "Attacker"
                contents = json.dumps(manifest).encode()
            altered.writestr(name, contents)
    result = verify_package(output.getvalue(), None)
    assert result["valid"] is False
    assert "Manifest signature is invalid." in result["errors"]


def test_report_rejects_unknown_investigation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/reports/forensic.pdf", json={"investigation_id": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404


def test_spill_geometry_metrics_are_derived_from_geojson() -> None:
    metrics = calculate_spill_metrics({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[72.8, 18.9], [72.9, 18.9], [72.9, 19.0], [72.8, 19.0], [72.8, 18.9]]]}, "properties": {}}]})
    assert metrics["component_count"] == 1
    assert metrics["area_km2"] > 100
    assert metrics["perimeter_km"] > 40
