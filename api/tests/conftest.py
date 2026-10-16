import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.models_registry  # noqa: F401
from app.core.config import settings
from app.core.database import Base, get_db
from app.features.auth import throttle
from app.main import app
from app.core.config import settings

TEST_URL = make_url(settings.database_url).set(database="rms_test")
engine = create_engine(TEST_URL, pool_pre_ping=True)
TestingSession = sessionmaker(bind=engine, autoflush=False)


def _override_get_db():
    s = TestingSession()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean():
    throttle.clear()
    with engine.begin() as c:
        c.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        for t in reversed(Base.metadata.sorted_tables):
            c.exec_driver_sql(f"TRUNCATE TABLE `{t.name}`")
        c.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
        c.exec_driver_sql("INSERT INTO counters (name, v) VALUES ('seq', 0)")
    yield


@pytest.fixture
def db():
    s = TestingSession()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photo_dir", str(tmp_path / "photos"))
