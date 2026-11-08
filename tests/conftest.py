import io
import logging
from pathlib import Path
import runpy
import sys
import time
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEMONITOR = REPO_ROOT / "semonitor.py"

# The golden data, test/<kind>/<sample>.<ext>, and is shared with test/test.sh.
GOLDEN_DIR = REPO_ROOT / "test"
SAMPLES = sorted(path.stem for path in (GOLDEN_DIR / "rec").glob("*.rec"))


class RunResult(NamedTuple):
    returncode: int
    stdout: bytes
    stderr: str


class _KeepOpenBytesIO(io.BytesIO):
    name = "<stdout>"

    def close(self):
        self.flush()


def _is_se_module(name):
    return name == "se" or name.startswith("se.")


def _exit_code(code):
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC0")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def golden_dir():
    return GOLDEN_DIR


@pytest.fixture
def golden(golden_dir):

    def path(kind, sample):
        return golden_dir / kind / f"{sample}.{kind}"

    return path


@pytest.fixture(params=SAMPLES)
def sample(request):
    return request.param


# Return a function that runs `semonitor.py ARGS` inside this process, to
# measure the coverage. The state semonitor keeps in module globals and in
# the logging setup is thrown away after each run, so the runs do not
# influence each other.
@pytest.fixture
def run_semonitor(monkeypatch):

    def run(*args):
        stdout = io.TextIOWrapper(
            _KeepOpenBytesIO(), encoding="latin-1", write_through=True
        )
        stderr = io.StringIO()

        root = logging.getLogger()
        handlers = root.handlers[:]
        level = root.level
        modules = {
            name: module
            for name, module in sys.modules.items()
            if _is_se_module(name)
        }
        for name in modules:
            del sys.modules[name]

        returncode = 0
        with monkeypatch.context() as patch:
            patch.setattr(sys, "argv", [str(SEMONITOR), *map(str, args)])
            patch.setattr(sys, "stdout", stdout)
            patch.setattr(sys, "stderr", stderr)
            try:
                runpy.run_path(str(SEMONITOR), run_name="__main__")
            except SystemExit as exit_:
                returncode = _exit_code(exit_.code)
            finally:
                for handler in root.handlers[:]:
                    if handler not in handlers:
                        root.removeHandler(handler)
                        handler.close()
                root.setLevel(level)
                for name in [n for n in sys.modules if _is_se_module(n)]:
                    del sys.modules[name]
                sys.modules.update(modules)

        return RunResult(
            returncode, stdout.buffer.getvalue(), stderr.getvalue()
        )

    return run
