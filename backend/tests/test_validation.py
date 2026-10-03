from fastapi.testclient import TestClient


def test_registration_validation_does_not_echo_password(client: TestClient) -> None:
    invalid_password = "test-secret" * 20
    response = client.post("/api/v1/auth/register", json={"email": "bad-email", "password": invalid_password,
                                                        "nickname": "test"})
    assert response.status_code == 422
    assert invalid_password not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])
