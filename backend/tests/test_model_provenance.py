"""Provenance contract tests. Generated weights are test fixtures, not trained evidence."""
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.system import router
from app.core.config import Settings, get_settings


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, model_weights_path=tmp_path / "model.pt",
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def checkpoint(tmp_path):
    torch = pytest.importorskip("torch")
    from app.ml.unet import build_unet
    torch.set_num_threads(1)
    path = tmp_path / "model.pt"
    torch.save({"model_state_dict": build_unet().state_dict(), "training_metadata": {
        "trained_at": "2026-09-13T10:00:00Z", "epoch": 2,
        "dataset_sample_count": 10, "validation_dice": 0.6,
    }}, path)
    return path


def write_sidecar(path, metadata, digest=None):
    path.with_name(path.name + ".metadata.json").write_text(json.dumps({
        "weights_sha256": digest or hashlib.sha256(path.read_bytes()).hexdigest(),
        "training_metadata": metadata,
    }))


@pytest.mark.parametrize("endpoint", ["info", "metrics"])
def test_missing_checkpoint_returns_503(client, endpoint):
    assert client.get(f"/api/model/{endpoint}").status_code == 503


def test_legacy_checkpoint_preserves_unknown_fields(client, checkpoint):
    response = client.get("/api/model/info")
    assert response.status_code == 200
    body = response.json()
    assert body["weights_sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert body["metrics"]["dice_score"] == 0.6
    assert body["metrics"]["iou"] is None
    assert body["input_shape"] is None
    assert body["dataset_provenance"] is None
    assert body["architecture_parameters"]["parameter_count"] > 0
    assert client.get("/api/model/metrics").json() == body["metrics"]
    assert response.headers["cache-control"] == "no-store"


def test_checksum_bound_supplement(client, checkpoint):
    write_sidecar(checkpoint, {"validation_iou": 0.4, "training_epochs": 3,
        "input_shape": [3, 256, 256], "dataset_provenance": {"purpose": "test fixture"}})
    response = client.get("/api/model/info")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["iou"] == 0.4
    assert body["metrics"]["training_epochs"] == 3
    assert body["missing_fields"] == []


@pytest.mark.parametrize("metadata,digest", [
    ({"validation_iou": 0.4}, "0" * 64),
    ({"validation_dice": 0.9}, None),
    ({"validation_iou": 1.1}, None),
    ({"input_shape": [1, 256, 256]}, None),
    ({"training_epochs": 1}, None),
])
def test_invalid_supplement_rejected(client, checkpoint, metadata, digest):
    write_sidecar(checkpoint, metadata, digest)
    assert client.get("/api/model/info").status_code == 503


def test_malformed_json_rejected(client, checkpoint):
    checkpoint.with_name(checkpoint.name + ".metadata.json").write_text('{broken')
    assert client.get("/api/model/info").status_code == 503


def test_incompatible_weights_rejected(client, checkpoint):
    import torch
    payload = torch.load(checkpoint, weights_only=True)
    payload["model_state_dict"] = {}
    torch.save(payload, checkpoint)
    assert client.get("/api/model/info").status_code == 503
