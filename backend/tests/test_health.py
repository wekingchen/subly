def test_health_smoke_without_lifespan(monkeypatch, tmp_path):
    """health smoke 不进入 lifespan，避免启动真实 scheduler 或初始化仓库数据目录。"""
    monkeypatch.chdir(tmp_path)

    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "configured" in response.json()
    assert response.headers.get("X-Request-ID")
