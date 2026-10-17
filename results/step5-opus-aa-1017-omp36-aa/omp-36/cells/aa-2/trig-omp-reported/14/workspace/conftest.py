import time
import pytest


@pytest.fixture(scope="session", autouse=True)
def warehouse_connection():
    time.sleep(8)  # connects to the reporting warehouse
    yield
