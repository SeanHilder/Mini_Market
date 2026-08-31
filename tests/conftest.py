import pytest
import os
import uuid
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from mini_market import create_app
from mini_market.db import get_db, init_db
from mini_market.carts import get_cart

@pytest.fixture(params=["sqlite", "postgres"])
def database_location(request, tmp_path):
    if request.param == "sqlite":
        yield str(tmp_path / "test.sqlite")
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL integration tests need a test database")
    schema = "mm_test_" + uuid.uuid4().hex
    native_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    admin = psycopg.connect(native_url, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_url(url).update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False)
    finally:
        # Only the randomly named schema created by this fixture is removed.
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


@pytest.fixture
def app(database_location):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATABASE": database_location})
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
    def snapshot():
        # Represents loading the form in a browser; callers may retain it to
        # simulate a second tab holding an old version.
        with client.session_transaction() as session:
            with client.application.app_context():
                cart = get_cart(get_db(), session["cart_id"])
            return {"csrf_token": session["csrf_token"], "cart_version": str(cart["version"]), "checkout_key": cart["checkout_key"]}
    return snapshot
