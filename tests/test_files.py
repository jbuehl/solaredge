import contextlib
import io
import logging
import re
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


def test_open_out_file_write_mode_never_overwrites_an_existing_file(workdir):
    (workdir / "out.json").write_bytes(b"old content")

    with files.open_out_file("out.json", "wb") as out_file:
        assert out_file.name == "out.1.json"
        out_file.write(b"new")

    assert (workdir / "out.json").read_bytes() == b"old content"
    assert (workdir / "out.1.json").read_bytes() == b"new"
    assert sorted(path.name for path in workdir.iterdir()) == [
        "out.1.json",
        "out.json",
    ]


def test_open_out_file_write_mode_skips_taken_numbered_names(workdir):
    for name in ("out.json", "out.1.json", "out.2.json"):
        (workdir / name).write_bytes(b"old")

    with files.open_out_file("out.json", "wb") as out_file:
        assert out_file.name == "out.3.json"
        out_file.write(b"new")

    assert (workdir / "out.3.json").read_bytes() == b"new"
    for name in ("out.json", "out.1.json", "out.2.json"):
        assert (workdir / name).read_bytes() == b"old"


def test_open_out_file_write_mode_keeps_the_directory_when_renaming(workdir):
    (workdir / "sub").mkdir()
    (workdir / "sub" / "out.rec").write_bytes(b"old")

    with files.open_out_file("sub/out.rec", "wb") as out_file:
        assert out_file.name == "sub/out.1.rec"

    assert (workdir / "sub" / "out.rec").read_bytes() == b"old"
    assert (workdir / "sub" / "out.1.rec").exists()


def test_open_out_file_write_mode_creates_missing_directories(workdir):
    with files.open_out_file("a/b/out.json", "wb") as out_file:
        assert out_file.name == "a/b/out.json"

    assert (workdir / "a" / "b" / "out.json").exists()


def test_open_out_file_append_mode_extends_the_same_file(workdir):
    (workdir / "out.json").write_bytes(b"old")

    with files.open_out_file("out.json", "ab") as out_file:
        out_file.write(b"+new")

    assert (workdir / "out.json").read_bytes() == b"old+new"
    assert [path.name for path in workdir.iterdir()] == ["out.json"]


def test_open_out_file_append_mode_creates_a_missing_file(workdir):
    files.open_out_file("out.json", "ab").close()

    assert (workdir / "out.json").read_bytes() == b""


@pytest.fixture
def today(monkeypatch):
    # Pin the clock used for __date__, but still run the real strftime on it so
    # the format string itself is exercised.
    real_strftime = files.time.strftime
    current = {"now": (2026, 1, 2, 12, 34, 56)}

    def strftime(fmt, *_):
        return real_strftime(fmt, (*current["now"], 0, 1, -1))

    monkeypatch.setattr(files.time, "strftime", strftime)

    def set_now(year, month, day, hour=12, minute=34, second=56):
        current["now"] = (year, month, day, hour, minute, second)

    return set_now


@pytest.mark.usefixtures("today")
def test_open_out_file_date_token_is_replaced_by_the_date(workdir):
    with files.open_out_file("out.__date__.json") as out_file:
        assert out_file.name == "out.20260102.json"
        out_file.write(b"{}")

    assert [path.name for path in workdir.iterdir()] == ["out.20260102.json"]
    assert (workdir / "out.20260102.json").read_bytes() == b"{}"


def test_open_out_file_date_is_zero_padded(today):
    today(2026, 3, 4)

    with files.open_out_file("out.__date__.json") as out_file:
        assert out_file.name == "out.20260304.json"


@pytest.mark.usefixtures("today")
def test_open_out_file_without_date_token_keeps_the_name():
    with files.open_out_file("out.json") as out_file:
        assert out_file.name == "out.json"


@pytest.mark.usefixtures("today")
def test_open_out_file_every_date_token_is_replaced(workdir):
    with files.open_out_file("__date__/out.__date__.json") as out_file:
        assert out_file.name == "20260102/out.20260102.json"

    assert (workdir / "20260102" / "out.20260102.json").exists()


@pytest.mark.usefixtures("today")
def test_open_out_file_date_token_works_in_the_directory_name(workdir):
    with files.open_out_file("data/__date__/out.rec") as out_file:
        assert out_file.name == "data/20260102/out.rec"

    assert (workdir / "data" / "20260102" / "out.rec").exists()


@pytest.mark.usefixtures("today")
def test_open_out_file_existing_dated_file_gets_a_counter(workdir):
    (workdir / "out.20260102.json").write_bytes(b"old")

    with files.open_out_file("out.__date__.json") as out_file:
        assert out_file.name == "out.20260102.1.json"
        out_file.write(b"new")

    assert (workdir / "out.20260102.json").read_bytes() == b"old"
    assert (workdir / "out.20260102.1.json").read_bytes() == b"new"


@pytest.mark.usefixtures("today")
def test_open_out_file_dated_file_counts_up_on_every_run():
    names = []
    for _ in range(4):
        with files.open_out_file("out.__date__.json") as out_file:
            names.append(out_file.name)

    assert names == [
        "out.20260102.json",
        "out.20260102.1.json",
        "out.20260102.2.json",
        "out.20260102.3.json",
    ]


def test_open_out_file_a_new_day_starts_again_without_a_counter(today, workdir):
    files.open_out_file("out.__date__.json").close()
    files.open_out_file("out.__date__.json").close()
    today(2026, 1, 3)

    with files.open_out_file("out.__date__.json") as out_file:
        assert out_file.name == "out.20260103.json"

    assert sorted(path.name for path in workdir.iterdir()) == [
        "out.20260102.1.json",
        "out.20260102.json",
        "out.20260103.json",
    ]


@pytest.mark.usefixtures("today")
def test_open_out_file_dated_append_mode_extends_the_dated_file(workdir):
    (workdir / "out.20260102.json").write_bytes(b"old")

    with files.open_out_file("out.__date__.json", "ab") as out_file:
        assert out_file.name == "out.20260102.json"
        out_file.write(b"+new")

    assert (workdir / "out.20260102.json").read_bytes() == b"old+new"
    assert [path.name for path in workdir.iterdir()] == ["out.20260102.json"]


@pytest.mark.usefixtures("today")
def test_open_out_file_dated_append_mode_creates_a_missing_file(workdir):
    files.open_out_file("out.__date__.json", "ab").close()

    assert (workdir / "out.20260102.json").read_bytes() == b""


@pytest.mark.usefixtures("today")
def test_open_out_file_datetime_token_is_replaced_by_date_and_time(workdir):
    with files.open_out_file("out.__datetime__.json") as out_file:
        assert out_file.name == "out.20260102123456.json"
        out_file.write(b"{}")

    assert [path.name for path in workdir.iterdir()] == [
        "out.20260102123456.json"
    ]


def test_open_out_file_datetime_is_zero_padded_and_24_hour(today):
    today(2026, 3, 4, 5, 6, 7)

    with files.open_out_file("out.__datetime__.json") as out_file:
        assert out_file.name == "out.20260304050607.json"

    today(2026, 3, 4, 17, 6, 7)

    with files.open_out_file("out.__datetime__.json") as out_file:
        assert out_file.name == "out.20260304170607.json"


def test_open_out_file_datetime_is_made_of_digits_only():
    with files.open_out_file("out.__datetime__.json") as out_file:
        name = out_file.name

    assert re.fullmatch(r"out\.\d{14}\.json", name)


@pytest.mark.usefixtures("today")
def test_open_out_file_date_and_datetime_tokens_do_not_clash():
    with files.open_out_file("__date__/out.__datetime__.json") as out_file:
        assert out_file.name == "20260102/out.20260102123456.json"


@pytest.mark.usefixtures("today")
def test_open_out_file_existing_datetime_file_gets_a_counter(workdir):
    (workdir / "out.20260102123456.json").write_bytes(b"old")

    with files.open_out_file("out.__datetime__.json") as out_file:
        assert out_file.name == "out.20260102123456.1.json"
        out_file.write(b"new")

    assert (workdir / "out.20260102123456.json").read_bytes() == b"old"
    assert (workdir / "out.20260102123456.1.json").read_bytes() == b"new"


def test_open_out_file_another_second_is_another_file_without_counter(today):
    files.open_out_file("out.__datetime__.json").close()
    today(2026, 1, 2, 12, 34, 57)

    with files.open_out_file("out.__datetime__.json") as out_file:
        assert out_file.name == "out.20260102123457.json"


@pytest.mark.usefixtures("today")
def test_open_out_file_datetime_append_mode_extends_the_same_file(workdir):
    (workdir / "out.20260102123456.json").write_bytes(b"old")

    with files.open_out_file("out.__datetime__.json", "ab") as out_file:
        assert out_file.name == "out.20260102123456.json"
        out_file.write(b"+new")

    assert (workdir / "out.20260102123456.json").read_bytes() == b"old+new"


def test_open_out_file_the_date_comes_from_the_current_time():
    before = files.time.strftime("%Y%m%d")
    with files.open_out_file("out.__date__.json") as out_file:
        name = out_file.name
    after = files.time.strftime("%Y%m%d")

    # tolerate the clock ticking over midnight during the test
    assert name in (f"out.{before}.json", f"out.{after}.json")


@pytest.mark.parametrize("mode", ["wb", "ab"])
def test_open_out_file_creates_missing_parent_directories(mode, workdir):
    with files.open_out_file("a/b/out.json", mode) as out_file:
        assert out_file.name == "a/b/out.json"
        out_file.write(b"{}")

    assert (workdir / "a" / "b" / "out.json").read_bytes() == b"{}"


def test_open_out_file_existing_parent_directories_are_reused(workdir):
    (workdir / "a").mkdir()
    (workdir / "a" / "keep.txt").write_bytes(b"keep")

    files.open_out_file("a/out.json").close()

    assert (workdir / "a" / "keep.txt").read_bytes() == b"keep"
    assert (workdir / "a" / "out.json").exists()


def test_open_out_file_parent_that_is_a_file_raises(workdir):
    (workdir / "a").write_bytes(b"not a directory")

    with pytest.raises(FileExistsError), files.open_out_file("a/out.json"):
        pytest.fail("open_out_file should not return a file")

    assert [path.name for path in workdir.iterdir()] == ["a"]


# --- next_free_file_name --------------------------------------------------------


def test_next_free_file_name_returns_an_unused_name_unchanged():
    assert files.next_free_file_name("out.json") == "out.json"


def test_next_free_file_name_inserts_the_counter_before_the_extension(workdir):
    (workdir / "out.json").write_bytes(b"")

    assert files.next_free_file_name("out.json") == "out.1.json"


def test_next_free_file_name_counts_up_past_existing_files(workdir):
    for name in ("out.json", "out.1.json", "out.2.json"):
        (workdir / name).write_bytes(b"")

    assert files.next_free_file_name("out.json") == "out.3.json"


def test_next_free_file_name_fills_no_gaps_before_the_first_free_slot(workdir):
    for name in ("out.json", "out.2.json"):
        (workdir / name).write_bytes(b"")

    assert files.next_free_file_name("out.json") == "out.1.json"


def test_next_free_file_name_handles_names_without_an_extension(workdir):
    (workdir / "out").write_bytes(b"")

    assert files.next_free_file_name("out") == "out.1"


def test_next_free_file_name_only_splits_the_last_extension(workdir):
    (workdir / "out.tar.gz").write_bytes(b"")

    assert files.next_free_file_name("out.tar.gz") == "out.tar.1.gz"


def test_next_free_file_name_treats_a_directory_as_free(workdir):
    # only regular files count as taken for the base name itself
    (workdir / "out.json").mkdir()

    assert files.next_free_file_name("out.json") == "out.json"


def test_next_free_file_name_skips_a_directory_at_a_numbered_name(workdir):
    (workdir / "out.json").write_bytes(b"")
    (workdir / "out.1.json").mkdir()

    assert files.next_free_file_name("out.json") == "out.2.json"


# --- close_out_files ---------------------------------------------------------


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
