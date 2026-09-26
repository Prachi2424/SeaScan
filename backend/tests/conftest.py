from datetime import UTC, datetime

import pytest

from app.auth.dependencies import get_current_user
from app.main import app
from app.schemas.auth import AuthUser


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
