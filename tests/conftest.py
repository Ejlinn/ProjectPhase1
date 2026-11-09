"""Test setup. Every test uses a temporary database and model folder, so the real
instance/epa_data.db and models_saved/ are never read or changed by the tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

TEST_DIR = Path(tempfile.mkdtemp(prefix="epa_tests_"))
TEST_DB = TEST_DIR / "test.db"
os.environ["EPA_DATABASE_URI"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["EPA_MODEL_PATH"] = str(TEST_DIR / "models" / "co2_predictor.joblib")

from app import app as flask_app  # noqa: E402  (must come after the env vars)
from models import FacilityRecord, UploadedDataset, db  # noqa: E402
import importtraci  # noqa: E402


@pytest.fixture(scope="session")
def app():
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        importtraci.load_factors(database=TEST_DB)
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def clean_db(app):
    """Empty the record tables before a test that writes its own rows."""
    with app.app_context():
        db.session.query(FacilityRecord).delete()
        db.session.query(UploadedDataset).delete()
        db.session.commit()
    yield


def add_records(rows):
    """rows: list of dicts with FacilityRecord field names."""
    with flask_app.app_context():
        for row in rows:
            db.session.add(FacilityRecord(**row))
        db.session.commit()
