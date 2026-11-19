def test_admin_index_renders(admin_client):
    response = admin_client.get("/admin/")
    assert response.status_code == 200
    assert "partitario" in response.content.decode()
