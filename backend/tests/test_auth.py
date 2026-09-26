import pytest

from app.auth.security import hash_password, verify_password


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("SecurePassword2026")
    second = hash_password("SecurePassword2026")
    assert first != second
    assert verify_password("SecurePassword2026", first)
    assert not verify_password("WrongPassword2026", first)


def test_role_dependency_rejects_unpermitted_user():
    from datetime import UTC, datetime
    from fastapi import HTTPException
    from app.auth.dependencies import require_roles
    from app.schemas.auth import AuthUser

    analyst = AuthUser(id="a", username="analyst", display_name="Analyst", role="analyst", active=True, created_at=datetime.now(UTC))
    with pytest.raises(HTTPException) as error:
        require_roles("administrator")(analyst)
    assert error.value.status_code == 403


@pytest.mark.real_auth
def test_login_and_role_enforcement(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import app

    monkeypatch.setenv("SEASCAN_DATABASE_URL", f"sqlite:///{tmp_path}/auth.db")
    monkeypatch.setenv("SEASCAN_ENVIRONMENT", "development")
    monkeypatch.setenv("SEASCAN_DEMO_USER_PASSWORD", "SeaScan@2026")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/investigations").status_code == 401

            analyst = client.post("/api/auth/login", json={"username": "analyst", "password": "SeaScan@2026"})
            assert analyst.status_code == 200
            analyst_headers = {"Authorization": f"Bearer {analyst.json()['access_token']}"}
            assert client.get("/api/investigations", headers=analyst_headers).status_code == 200
            assert client.post("/api/investigations", headers=analyst_headers, json={"title": "Denied case"}).status_code == 403

            investigator = client.post("/api/auth/login", json={"username": "investigator", "password": "SeaScan@2026"})
            investigator_headers = {"Authorization": f"Bearer {investigator.json()['access_token']}"}
            assert client.post("/api/investigations", headers=investigator_headers, json={"title": "Permitted case"}).status_code == 201

            administrator = client.post("/api/auth/login", json={"username": "admin", "password": "SeaScan@2026"})
            admin_headers = {"Authorization": f"Bearer {administrator.json()['access_token']}"}
            users = client.get("/api/auth/users", headers=admin_headers)
            assert users.status_code == 200
            assert {user["role"] for user in users.json()} == {"investigator", "analyst", "administrator"}
            created = client.post("/api/auth/users", headers=admin_headers, json={
                "username": "reviewer", "display_name": "Case Reviewer", "role": "analyst", "password": "SecureReview2026",
            })
            assert created.status_code == 201
            changed = client.patch(f"/api/auth/users/{created.json()['id']}", headers=admin_headers, json={"role": "investigator", "active": False})
            assert changed.status_code == 200
            assert changed.json()["role"] == "investigator"
            assert changed.json()["active"] is False
    finally:
        get_settings.cache_clear()
