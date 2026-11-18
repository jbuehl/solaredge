import contextlib
import io
import logging
import sys
from pathlib import Path

import pytest

from se import files

LOGGER = "se.files"


@pytest.fixture
def messages(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    def logged():
        return [
            record.getMessage()
            for record in caplog.records
            if record.name == LOGGER
        ]

    return logged


# --- open_in_file --------------------------------------------------------------


def test_open_in_file_stdin_gives_the_binary_stdin_buffer(monkeypatch):
    stdin = io.TextIOWrapper(io.BytesIO(b"\x12\x34\x56\x79"))
    monkeypatch.setattr(sys, "stdin", stdin)

    with files.open_in_file("stdin") as in_file:
        assert in_file is stdin.buffer
        assert in_file.read() == b"\x12\x34\x56\x79"


def test_open_in_file_opens_a_path_for_binary_reading(workdir):
    path = workdir / "in.rec"
    path.write_bytes(b"\x00\xff\x7f")

    with files.open_in_file(str(path)) as in_file:
        assert in_file.mode == "rb"
        assert in_file.name == str(path)
        assert in_file.read() == b"\x00\xff\x7f"


def test_open_in_file_only_treats_the_exact_word_stdin_specially(
    workdir, monkeypatch
):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"other")))
    (workdir / "stdin.rec").write_bytes(b"data")

    with files.open_in_file("stdin.rec") as in_file:
        assert in_file.read() == b"data"


def test_open_in_file_missing_file_raises():
    missing = "does-not-exist.rec"

    with pytest.raises(FileNotFoundError), files.open_in_file(missing):
        pass


# --- open_serial --------------------------------------------------------------


def test_open_serial_passes_device_and_baud_rate_to_pyserial(monkeypatch):
    calls = []
    port = object()

    def fake_serial(*args, **kwargs):
        calls.append((args, kwargs))
        return port

    monkeypatch.setattr(files.serial, "Serial", fake_serial)

    assert files.open_serial("/dev/ttyUSB0", 115200) is port
    assert calls == [(("/dev/ttyUSB0",), {"baudrate": 115200})]


# --- close_data ---------------------------------------------------------------


def test_close_data_closes_the_file_and_logs_its_name(workdir, messages):
    path = workdir / "in.rec"
    path.write_bytes(b"")

    with path.open("rb") as data_file:
        files.close_data(data_file)

        assert data_file.closed
    assert messages() == [f"closing {path}"]


def test_close_data_flushes_a_written_file(workdir):
    path = workdir / "data.bin"

    with path.open("wb") as data_file:
        data_file.write(b"buffered")
        files.close_data(data_file)

    assert path.read_bytes() == b"buffered"


# --- open_out_file -------------------------------------------------------------


@pytest.mark.parametrize("name", [None, ""])
def test_open_out_file_without_a_name_opens_nothing(name, workdir):
    out_file = files.open_out_file(name)
    try:
        assert out_file is None
    finally:
        if out_file is not None:
            out_file.close()
    assert list(workdir.iterdir()) == []


@pytest.mark.parametrize("mode", ["wb", "ab"])
def test_open_out_file_creates_the_file_in_the_given_mode(mode, workdir):
    with files.open_out_file("out.json", mode) as out_file:
        assert out_file.mode == mode
        assert out_file.name == "out.json"
        out_file.write(b"{}")

    assert (workdir / "out.json").read_bytes() == b"{}"


def test_open_out_file_defaults_to_write_mode():
    with files.open_out_file("out.json") as out_file:
        assert out_file.mode == "wb"


def test_open_out_file_write_mode_truncates_an_existing_file(workdir):
    (workdir / "out.json").write_bytes(b"old content")

    with files.open_out_file("out.json", "wb") as out_file:
        out_file.write(b"new")

    assert (workdir / "out.json").read_bytes() == b"new"
    assert [path.name for path in workdir.iterdir()] == ["out.json"]


def test_open_out_file_append_mode_extends_the_same_file(workdir):
    (workdir / "out.json").write_bytes(b"old")

    with files.open_out_file("out.json", "ab") as out_file:
        out_file.write(b"+new")

    assert (workdir / "out.json").read_bytes() == b"old+new"
    assert [path.name for path in workdir.iterdir()] == ["out.json"]


def test_open_out_file_append_mode_creates_a_missing_file(workdir):
    files.open_out_file("out.json", "ab").close()

    assert (workdir / "out.json").read_bytes() == b""


def test_open_out_file_missing_directory_raises(workdir):
    missing = "missing/out.json"

    with pytest.raises(FileNotFoundError), files.open_out_file(missing):
        pass

    assert list(workdir.iterdir()) == []


# --- close_out_files -----------------------------------------------------------


@pytest.mark.parametrize("with_rec", [False, True], ids=["no-rec", "rec"])
@pytest.mark.parametrize("with_out", [False, True], ids=["no-out", "out"])
def test_close_out_files_closes_and_logs_only_the_given_files(
    with_rec, with_out, workdir, messages
):
    expected = []
    if with_rec:
        expected.append(f"closing {workdir / 'rec.bin'}")
    if with_out:
        expected.append(f"closing {workdir / 'out.json'}")

    with contextlib.ExitStack() as stack:
        rec_file = (
            stack.enter_context((workdir / "rec.bin").open("wb"))
            if with_rec
            else None
        )
        out_file = (
            stack.enter_context((workdir / "out.json").open("wb"))
            if with_out
            else None
        )

        files.close_out_files(rec_file, out_file)

        assert rec_file is None or rec_file.closed
        assert out_file is None or out_file.closed
    assert messages() == expected


def test_close_out_files_flushes_buffered_data(workdir):
    with (workdir / "out.json").open("wb") as out_file:
        out_file.write(b"buffered")
        files.close_out_files(None, out_file)

    assert (workdir / "out.json").read_bytes() == b"buffered"


def test_close_out_files_round_trips_with_open_out_file():
    with (
        files.open_out_file("rec.bin") as rec_file,
        files.open_out_file("out.json") as out_file,
    ):
        rec_file.write(b"rec")
        out_file.write(b"out")
        files.close_out_files(rec_file, out_file)

    assert Path("rec.bin").read_bytes() == b"rec"
    assert Path("out.json").read_bytes() == b"out"
