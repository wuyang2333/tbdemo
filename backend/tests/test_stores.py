from backend.app.api import stores as stores_api


def test_manual_sycm_test_forces_fresh_login_check(client, admin_token, monkeypatch):
    forced = []

    def fake_check(store, *, force=False):
        forced.append((store["id"], force))
        return {"ok": True}

    monkeypatch.setattr(stores_api, "check_sycm_login", fake_check)

    response = client.post(
        "/api/stores/1/sycm/test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert forced == [(1, True)]
