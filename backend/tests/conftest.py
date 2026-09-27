from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthUser
from app.services.signing import generate_private_key


@pytest.fixture(autouse=True)
def authenticated_test_user(request):
    """Keep legacy endpoint tests focused while dedicated auth tests exercise real sessions."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="test-administrator",
        username="test-admin",
        display_name="Test Administrator",
        role="administrator",
        active=True,
        created_at=datetime.now(UTC),
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def configured_signing_key(tmp_path, monkeypatch):
    key_path = tmp_path / "test-signing-key.pem"
    generate_private_key(key_path)
    monkeypatch.setenv("SEASCAN_SIGNING_PRIVATE_KEY_PATH", str(key_path))
    monkeypatch.setenv("SEASCAN_SIGNING_IDENTITY", "SeaScan automated test signer")
    get_settings.cache_clear()
    yield key_path
    get_settings.cache_clear()
