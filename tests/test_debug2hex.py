import io
from pathlib import Path
import runpy
import sys

import pytest

import se.logutils

SCRIPT = Path(__file__).resolve().parent.parent / "utilities" / "debug2hex.py"


class Stdout(io.TextIOWrapper):
    pass


def run_debug2hex(monkeypatch, *args):
    stdout = Stdout(io.BytesIO(), encoding="latin-1", write_through=True)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdout", stdout)
    code = 0
    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else 1
    stdout.flush()
    return code, stdout.buffer.getvalue()


def write_log(workdir, text, name="debug.log"):
    path = workdir / name
    path.write_text(text)
    return path


# --- to a file ---------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #47")
def test_the_data_lines_are_written_as_binary_to_the_data_file(
    workdir, monkeypatch
):
    log = write_log(workdir, "data:       12 34 56 79\ndata:       00 ff\n")

    code, stdout = run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert code == 0
    assert stdout == b""
    assert (workdir / "out.bin").read_bytes() == b"\x12\x34\x56\x79\x00\xff"


@pytest.mark.xfail(strict=True, reason="Issue #47")
def test_lines_that_are_not_data_are_ignored(workdir, monkeypatch):
    log = write_log(
        workdir,
        "DEBUG starting\n"
        "data:       01 02\n"
        "message: 12 length: 2\n"
        "   data:       ff\n"
        "\n"
        "data:       03\n",
    )

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert (workdir / "out.bin").read_bytes() == b"\x01\x02\x03"


@pytest.mark.xfail(strict=True, reason="Issue #47")
@pytest.mark.parametrize(
    "line",
    [
        "data: 0a 0B 0c",
        "data:0a0b0c",
        "data:       0a 0b 0c   ",
        "data:\t0a 0B 0c\t",
    ],
)
def test_spacing_and_the_case_of_the_hex_digits_do_not_matter(
    workdir, monkeypatch, line
):
    log = write_log(workdir, line + "\n")

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert (workdir / "out.bin").read_bytes() == b"\x0a\x0b\x0c"


def test_a_log_without_data_gives_an_empty_file(workdir, monkeypatch):
    log = write_log(workdir, "nothing to see here\n")

    code, _ = run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert code == 0
    assert (workdir / "out.bin").read_bytes() == b""


def test_an_empty_log_gives_an_empty_file(workdir, monkeypatch):
    log = write_log(workdir, "")

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert (workdir / "out.bin").read_bytes() == b""


@pytest.mark.xfail(strict=True, reason="Issue #47")
def test_the_data_file_is_replaced_not_extended(workdir, monkeypatch):
    (workdir / "out.bin").write_bytes(b"old data")
    log = write_log(workdir, "data:       01\n")

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert (workdir / "out.bin").read_bytes() == b"\x01"


@pytest.mark.xfail(strict=True, reason="Issue #47")
# No buffered data that is only written at the exit of the interpreter, as a
# script that is used in a pipeline is read right after it ends.
def test_the_data_file_is_complete_when_the_script_has_ended(
    workdir, monkeypatch
):
    log = write_log(workdir, "data:       01 02 03\n")
    opened = []
    real_open = open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert all(handle.closed for handle in opened)


# --- to stdout ---------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #48")
def test_without_a_data_file_the_binary_data_goes_to_stdout(
    workdir, monkeypatch
):
    log = write_log(workdir, "data:       12 34 56 79\ndata:       80 ff\n")

    code, stdout = run_debug2hex(monkeypatch, log)

    assert code == 0
    assert stdout == b"\x12\x34\x56\x79\x80\xff"


# --- errors ------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #31")
def test_a_log_file_has_to_be_given(monkeypatch):
    code, _ = run_debug2hex(monkeypatch)

    assert code not in (0, None)


def test_a_log_file_that_does_not_exist_is_an_error(workdir, monkeypatch):
    with pytest.raises(FileNotFoundError):
        run_debug2hex(monkeypatch, workdir / "missing.log")


@pytest.mark.xfail(strict=True, reason="Issue #47")
def test_data_that_is_not_hex_is_an_error(workdir, monkeypatch):
    log = write_log(workdir, "data:       zz yy\n")

    with pytest.raises(ValueError):
        run_debug2hex(monkeypatch, log, workdir / "out.bin")


# --- log of semonitor itself -------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #47")
@pytest.mark.parametrize(
    "data",
    [
        bytes(range(256)),
        b"\x12\x34\x56\x79" + bytes(60),
        b"\x00",
        b"x" * 17,
    ],
)
def test_what_semonitor_logs_for_data_gives_the_data_back(
    workdir, monkeypatch, data
):
    log = write_log(workdir, "\n".join(se.logutils.format_data(data)) + "\n")

    run_debug2hex(monkeypatch, log, workdir / "out.bin")

    assert (workdir / "out.bin").read_bytes() == data
