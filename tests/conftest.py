import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest

from app import create_app
from extensions import db as _db
from models import Vendedor


@pytest.fixture()
def app():
    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def vendedor(db):
    v = Vendedor(username="vend1", nombre="Vendedor Uno", is_admin=False)
    v.set_password("clave123")
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture()
def admin(db):
    a = Vendedor(username="admin1", nombre="Admin Uno", is_admin=True)
    a.set_password("clave123")
    db.session.add(a)
    db.session.commit()
    return a


def login(client, username, password):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=True
    )
