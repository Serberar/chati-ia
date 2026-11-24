import shutil
import tempfile
from pathlib import Path

from infra import paths

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="chati_tests_"))
paths.DATA_DIR = _TEST_ROOT / "data"
paths.OUTPUT_DIR = _TEST_ROOT / "outputs"
paths.DATA_DIR.mkdir(parents=True)
paths.OUTPUT_DIR.mkdir(parents=True)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)

from api import security

security.LOCAL_HOSTS.add("testserver")
