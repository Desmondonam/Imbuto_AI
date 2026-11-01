import pytest
from fastapi.testclient import TestClient

from imbuto.api.main import create_app
from imbuto.core.service import Imbuto
from imbuto.settings import Settings


@pytest.fixture(scope="session")
def core(tmp_path_factory):
    return Imbuto(Settings(db_path=tmp_path_factory.mktemp("db") / "test.sqlite"))


@pytest.fixture(scope="session")
def client(core):
    return TestClient(create_app(core))
