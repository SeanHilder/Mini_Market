import pytest
from mini_market import create_app
from mini_market.db import get_db, init_db

@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATABASE": str(tmp_path / "test.sqlite")})
    with app.app_context():
        init_db()
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def database(app):
    with app.app_context():
        yield get_db()

@pytest.fixture
def form(client):
    client.get("/")
    with client.session_transaction() as session:
        return {"csrf_token": session["csrf_token"]}
