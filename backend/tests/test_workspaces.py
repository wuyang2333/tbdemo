def test_workspace_scaffolds_are_registered(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}

    expected = {
        "/api/content": 6,
        "/api/monitoring": 6,
        "/api/market": 3,
        "/api/growth-lab": 5,
        "/api/ops-knowledge": 4,
    }
    for path, section_count in expected.items():
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()["sections"]) == section_count


def test_workspace_section_rejects_unknown_page(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    for path in ("/api/content", "/api/monitoring", "/api/market"):
        response = client.get(f"{path}/not-a-page", headers=headers)
        assert response.status_code == 404
