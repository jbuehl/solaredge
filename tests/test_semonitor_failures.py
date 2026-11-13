import os
import subprocess
import sys

import pytest

from .conftest import REPO_ROOT, SEMONITOR

SAMPLE = "Geoff99.190801.1135.test"
DEADLINE = 20  # seconds, only used up when something is wrong

# Pyserial only lists the ports that exist, so a port that does not exist is
# added to the list, to have semonitor try to open it.
LAUNCHER = """
import runpy, sys
import serial.tools.list_ports

port, script, *argv = sys.argv[1:]
sys.argv[:] = [script, *argv]
serial.tools.list_ports.comports = lambda: [(port, "missing", "n/a")]
runpy.run_path(script, run_name="__main__")
"""


def run(workdir, *args, listed_port=None):
    command = [sys.executable, str(SEMONITOR), *args]
    if listed_port:
        command = [sys.executable, "-c", LAUNCHER, listed_port, *command[1:]]
    return subprocess.run(
        command,
        cwd=workdir,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=DEADLINE,
        check=False,
    )


# A failure ends with a status that is not 0, so that a container restarts,
# and says what failed. How it says that is not part of the test.
def test_a_missing_input_file_is_a_failure(workdir):
    result = run(workdir, "missing.rec")

    assert result.returncode != 0
    assert "missing.rec" in result.stderr


def test_a_port_that_can_not_be_opened_is_a_failure(workdir):
    port = str(workdir / "ttySE0")

    result = run(workdir, "-t", "4", port, listed_port=port)

    assert result.returncode != 0
    assert port in result.stderr


@pytest.mark.parametrize("option", ["-o", "-r"])
def test_an_output_file_that_can_not_be_created_is_a_failure(
    workdir, golden, option
):
    (workdir / "blocker").write_text("a file, where a directory is needed")

    result = run(workdir, option, "blocker/out", golden("rec", SAMPLE))

    assert result.returncode != 0
    assert "blocker" in result.stderr
