import pytest

from cbv import ratelimit


@pytest.fixture(autouse=True)
def no_tries_yet():
    """The rate limits count in the server's memory: each test starts with none counted."""
    ratelimit.reset()
