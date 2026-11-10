import datetime as dt
from pathlib import Path
import runpy
import sys
import time as real_time
import types

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "utilities" / "se2file.py"
CLOCK_START = dt.datetime(2016, 1, 1, 12, 30, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self):
        self.now = CLOCK_START
        self.sleeps = []

    def advance(self, **kwargs):
        self.now += dt.timedelta(**kwargs)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds=seconds)

    def time(self):
        return (
            self.now - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
        ).total_seconds()


class InputExhausted(BaseException):
    pass


class Input:
    def __init__(self, clock, *items, then_stop=False):
        self.clock = clock
        self.items = list(items)
        self.then_stop = then_stop

    def readline(self):
        if not self.items:
            if self.then_stop:
                raise InputExhausted
            return ""
        item = self.items.pop(0)
        if isinstance(item, dt.timedelta):
            self.clock.now += item
            return self.readline()
        return item


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()

    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now

    fake_datetime = types.ModuleType("datetime")
    fake_datetime.datetime = FakeDatetime
    fake_datetime.timedelta = dt.timedelta
    fake_time = types.ModuleType("time")
    fake_time.__dict__.update(
        {k: v for k, v in vars(real_time).items() if not k.startswith("__")}
    )
    fake_time.time = clock.time
    fake_time.sleep = clock.sleep
    monkeypatch.setitem(sys.modules, "datetime", fake_datetime)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    return clock


@pytest.fixture
def se2file(clock, monkeypatch):

    def run(*args, stdin=(), then_stop=False):
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
        monkeypatch.setattr(
            sys, "stdin", Input(clock, *stdin, then_stop=then_stop)
        )
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        except SystemExit as exit_:
            return exit_.code if isinstance(exit_.code, int) else 1
        return 0

    return run


@pytest.fixture
def getargs(clock, monkeypatch):
    namespace = runpy.run_path(str(SCRIPT), run_name="se2file")

    def parse(*args):
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
        return namespace["getargs"]()

    return parse


# --- command line ------------------------------------------------------------


def test_the_base_directory_is_required(getargs, capsys):
    with pytest.raises(SystemExit) as exit_:
        getargs()

    assert exit_.value.code == 2
    assert "-b" in capsys.readouterr().err


def test_defaults(getargs):
    args = getargs("-b", "out")

    assert args.basedir == "out"
    assert args.prefix == "solardata_"
    assert args.debug is False
    assert args.store_daily is False
    assert args.looper is False
    assert args.make_daily_dir is False
    assert int(args.openfilesecs) == 120
    assert args.infile == "stdin"


def test_every_option_is_parsed(getargs):
    args = getargs(
        "-v", "-b", "out", "-p", "pre_", "-d", "-t", "30", "-w", "-m", "in.json"
    )

    assert args.debug is True
    assert args.prefix == "pre_"
    assert args.store_daily is True
    assert int(args.openfilesecs) == 30
    assert args.looper is True
    assert args.make_daily_dir is True
    assert args.infile == "in.json"


def test_waiting_forever_on_a_file_is_refused_with_a_warning(getargs, capsys):
    args = getargs("-b", "out", "-w", "in.json")

    assert "Warning" in capsys.readouterr().out
    assert args.infile == "in.json"


def test_waiting_forever_on_stdin_gives_no_warning(getargs, capsys):
    getargs("-b", "out", "-w")

    assert capsys.readouterr().out == ""


def test_unknown_options_are_refused(getargs):
    with pytest.raises(SystemExit) as exit_:
        getargs("-b", "out", "--no-such-option")

    assert exit_.value.code == 2


# --- files that are written --------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_each_line_of_a_file_is_appended_to_the_hourly_file(workdir, se2file):
    (workdir / "in.json").write_text('{"a": 1}\n{"b": 2}\n')
    (workdir / "out").mkdir()

    assert se2file("-b", "out", workdir / "in.json") == 0

    assert (workdir / "out" / "solardata_2016-01-01-12.json").read_text() == (
        '{"a": 1}\n{"b": 2}\n'
    )


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_lines_are_stripped_and_blank_lines_are_not_stored(workdir, se2file):
    (workdir / "in.json").write_text('  {"a": 1}  \r\n\n   \n{"b": 2}\n')
    (workdir / "out").mkdir()

    se2file("-b", "out", workdir / "in.json")

    assert (workdir / "out" / "solardata_2016-01-01-12.json").read_text() == (
        '{"a": 1}\n{"b": 2}\n'
    )


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_stdin_is_the_default_input(workdir, se2file):
    (workdir / "out").mkdir()

    se2file("-b", "out", stdin=['{"a": 1}\n'])

    assert (
        workdir / "out" / "solardata_2016-01-01-12.json"
    ).read_text() == '{"a": 1}\n'


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_existing_files_are_extended_and_not_overwritten(workdir, se2file):
    (workdir / "out").mkdir()
    existing = workdir / "out" / "solardata_2016-01-01-12.json"
    existing.write_text('{"old": 0}\n')

    se2file("-b", "out", stdin=['{"a": 1}\n'])

    assert existing.read_text() == '{"old": 0}\n{"a": 1}\n'


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_the_prefix_is_used_in_the_file_name(workdir, se2file):
    (workdir / "out").mkdir()

    se2file("-b", "out", "-p", "site-", stdin=['{"a": 1}\n'])

    assert (workdir / "out" / "site-2016-01-01-12.json").is_file()


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_daily_files_have_the_day_but_not_the_hour_in_their_name(
    workdir, se2file
):
    (workdir / "out").mkdir()

    se2file("-b", "out", "-d", stdin=['{"a": 1}\n'])

    assert [path.name for path in (workdir / "out").iterdir()] == [
        "solardata_2016-01-01.json"
    ]


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_new_hour_starts_a_new_file(workdir, se2file):
    (workdir / "out").mkdir()

    se2file(
        "-b",
        "out",
        stdin=[
            '{"a": 1}\n',
            dt.timedelta(hours=1),
            '{"b": 2}\n',
        ],
    )

    assert sorted(path.name for path in (workdir / "out").iterdir()) == [
        "solardata_2016-01-01-12.json",
        "solardata_2016-01-01-13.json",
    ]


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_new_hour_does_not_start_a_new_daily_file(workdir, se2file):
    (workdir / "out").mkdir()

    se2file(
        "-b",
        "out",
        "-d",
        stdin=['{"a": 1}\n', dt.timedelta(hours=1), '{"b": 2}\n'],
    )

    (path,) = (workdir / "out").iterdir()
    assert path.read_text() == '{"a": 1}\n{"b": 2}\n'


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_new_day_starts_a_new_daily_file(workdir, se2file):
    (workdir / "out").mkdir()

    se2file(
        "-b",
        "out",
        "-d",
        stdin=['{"a": 1}\n', dt.timedelta(days=1), '{"b": 2}\n'],
    )

    assert sorted(path.name for path in (workdir / "out").iterdir()) == [
        "solardata_2016-01-01.json",
        "solardata_2016-01-02.json",
    ]


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_directory_per_day_is_made_on_request(workdir, se2file):
    (workdir / "out").mkdir()

    se2file(
        "-b",
        "out",
        "-m",
        stdin=['{"a": 1}\n', dt.timedelta(days=1), '{"b": 2}\n'],
    )

    assert (
        workdir / "out" / "2016-01-01" / "solardata_2016-01-01-12.json"
    ).is_file()
    assert (
        workdir / "out" / "2016-01-02" / "solardata_2016-01-02-12.json"
    ).is_file()


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_directory_per_day_that_exists_is_used(workdir, se2file):
    (workdir / "out" / "2016-01-01").mkdir(parents=True)

    se2file("-b", "out", "-m", "-d", stdin=['{"a": 1}\n'])

    assert (
        workdir / "out" / "2016-01-01" / "solardata_2016-01-01.json"
    ).is_file()


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_the_output_files_are_not_left_open(workdir, se2file, monkeypatch):
    (workdir / "out").mkdir()
    opened = []
    real_open = open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)

    se2file("-b", "out", stdin=['{"a": 1}\n'])

    assert opened
    assert all(handle.closed for handle in opened)


# --- when to stop ------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_file_is_processed_once_and_then_the_script_ends(
    workdir, se2file, clock
):
    (workdir / "in.json").write_text('{"a": 1}\n')
    (workdir / "out").mkdir()

    assert se2file("-b", "out", workdir / "in.json") == 0

    # After the end of the file, only a limited time is spent waiting for more.
    assert 0 < len(clock.sleeps) <= 20


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_waiting_forever_on_stdin_goes_on_after_many_blank_lines(
    workdir, se2file
):
    (workdir / "out").mkdir()

    with pytest.raises(InputExhausted):
        se2file(
            "-b",
            "out",
            "-w",
            stdin=[""] * 50 + ['{"late": 1}\n'],
            then_stop=True,
        )

    assert (workdir / "out" / "solardata_2016-01-01-12.json").read_text() == (
        '{"late": 1}\n'
    )


def test_stdin_without_waiting_forever_ends_after_a_few_blank_lines(
    workdir, se2file
):
    (workdir / "out").mkdir()

    se2file("-b", "out", stdin=[""] * 50 + ['{"late": 1}\n'])

    assert list((workdir / "out").iterdir()) == []


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_a_blank_line_count_is_reset_by_data(workdir, se2file):
    (workdir / "out").mkdir()
    items = ([""] * 8 + ['{"a": 1}\n']) * 3

    se2file("-b", "out", stdin=items)

    assert (workdir / "out" / "solardata_2016-01-01-12.json").read_text().count(
        "\n"
    ) == 3


def test_the_script_waits_between_blank_reads(se2file, workdir, clock):
    (workdir / "out").mkdir()

    se2file("-b", "out", stdin=[""] * 3)

    assert clock.sleeps
    assert all(seconds > 0 for seconds in clock.sleeps)


# --- errors ------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #46")
def test_a_file_that_cannot_be_opened_is_reported_and_ends_with_one(
    se2file, workdir, capsys
):
    (workdir / "out").mkdir()

    assert se2file("-b", "out", "missing.json") == 1

    assert "missing.json" in capsys.readouterr().out


def test_a_missing_base_directory_is_an_error_not_silently_ignored(
    workdir, se2file
):
    with pytest.raises(OSError):
        se2file("-b", "does-not-exist", stdin=['{"a": 1}\n'])


# --- debug -------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_debug_shows_the_data_that_is_received(workdir, se2file, capsys):
    (workdir / "out").mkdir()

    se2file("-v", "-b", "out", stdin=['{"a": 1}\n'])

    assert 'Got some data: {"a": 1}' in capsys.readouterr().out


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_without_debug_nothing_is_printed(workdir, se2file, capsys):
    (workdir / "out").mkdir()

    se2file("-b", "out", stdin=['{"a": 1}\n'])

    assert capsys.readouterr().out == ""


@pytest.mark.xfail(strict=True, reason="Issue #16")
def test_debug_shows_a_new_file_name(workdir, se2file, capsys):
    (workdir / "out").mkdir()

    se2file("-v", "-b", "out", stdin=['{"a": 1}\n'])

    assert "solardata_2016-01-01-12.json" in capsys.readouterr().out


@pytest.mark.xfail(strict=True, reason="Issue #32")
def test_debug_reports_the_loop_count_with_a_readable_time(
    workdir, se2file, capsys
):
    (workdir / "out").mkdir()

    with pytest.raises(InputExhausted):
        se2file(
            "-v", "-b", "out", "-w", stdin=['{"a": 1}\n'] * 60, then_stop=True
        )

    out = capsys.readouterr().out
    # %M (minutes) and %S (seconds), not %m (month) and %s (epoch)
    assert "We've looped 60 times at 2016-01-01-12:30:00" in out
