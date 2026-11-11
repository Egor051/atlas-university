"""Bind the test process to a disposable database before test collection."""
import atexit
import os
from pathlib import Path
import sys
import tempfile

import pytest


def pytest_sessionstart(session):
    if 'app.db' in sys.modules:
        pytest.exit('Database was imported before pytest configured an isolated database.', returncode=1)
    directory = tempfile.TemporaryDirectory(prefix='atlas-tests-')
    atexit.register(directory.cleanup)
    os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(directory.name) / 'test.db').as_posix()
    from app.db import engine
    atexit.register(engine.dispose)
