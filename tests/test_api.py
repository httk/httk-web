from pathlib import Path

from starlette.testclient import TestClient

from httk.web.api import create_asgi_app, publish


def test_create_asgi_app_serves_content(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "content").mkdir(parents=True)
    (src / "static").mkdir(parents=True)
    (src / "templates").mkdir(parents=True)
    (src / "content" / "index.md").write_text("hello", encoding="utf-8")

    app = create_asgi_app(src)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "hello" in response.text


def test_publish_writes_html_output(tmp_path: Path) -> None:
    src = tmp_path / "src"
    out = tmp_path / "public"
    (src / "content").mkdir(parents=True)
    (src / "static").mkdir(parents=True)
    (src / "templates").mkdir(parents=True)
    (src / "content" / "index.md").write_text("hello", encoding="utf-8")

    report = publish(src, out, "http://localhost/")

    index_out = out / "index.html"
    assert index_out.exists()
    assert any(path == index_out for path in report.written_files)
