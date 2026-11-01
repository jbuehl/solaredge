import datetime
import logging
import sys
import time
from types import SimpleNamespace

import pytest

import se.commands
import se.data
import se.env
import se.msg

from .test_semonitor import (
    FROZEN_TIME,
    MASTER_MODE,
    carries_data,
    function_of,
    load_semonitor,
    make_args,
    make_files,
    recorded_messages,
)

POST_DATA = se.commands.PROT_CMD_SERVER_POST_DATA
# the recording with the end-of-day event (Type 0) of inverter 73124CBA, in
# its 7th performance data message
EOD_RECORDING = "oliv3r-20180218"
EOD_LINE = 7
# the recording with wake events (Type 1), and no end-of-day event
WAKE_RECORDING = "d-tamm-20160809"
TZ_EUROPE = "CET-1CEST,M3.5.0,M10.5.0/3"  # clocks go back on 2026-10-25


@pytest.fixture
def sm():
    return load_semonitor()


@pytest.fixture
def files():
    return make_files()


@pytest.fixture
def local_zone(monkeypatch):

    def set_zone(zone):
        monkeypatch.setenv("TZ", zone)
        time.tzset()

    yield set_zone
    monkeypatch.undo()
    time.tzset()


def event_types(msg):
    # the types of the events in a performance data message
    data = se.msg.parseMsg(msg)[4]
    events = se.data.parseData(POST_DATA, data)["events"]
    return {e.get("Type") for e in events.values()}


def messages_with_event(recording, wanted):
    return [
        msg
        for msg in recorded_messages(recording)
        if function_of(msg) == POST_DATA
        and carries_data(msg)
        and wanted in event_types(msg)
    ]


def local(epoch):
    return datetime.datetime.fromtimestamp(epoch)


# --- -n argument -------------------------------------------------------------


@pytest.fixture
def get_nadir(monkeypatch):

    def run(value):
        monkeypatch.setattr(sys, "argv", ["semonitor.py", "-n", value])
        return se.env.getArgs()[0].nadir

    return run


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("default", datetime.time(1, 40)),
        ("DEFAULT", datetime.time(1, 40)),
        ("0:00", datetime.time(0, 0)),
        ("04:05", datetime.time(4, 5)),
        ("23:59", datetime.time(23, 59)),
        ("event", se.env.NADIR_EVENT),
        ("EVENT", se.env.NADIR_EVENT),
    ],
)
def test_nadir_accepts_a_time_default_or_event(get_nadir, value, expected):
    assert get_nadir(value) == expected


@pytest.mark.parametrize("value", ["25:00", "1:60", "1:40am", "reset", ""])
def test_nadir_rejects_other_values(get_nadir, capsys, value):
    with pytest.raises(SystemExit) as exit_:
        get_nadir(value)

    assert exit_.value.code == 2
    assert "Invalid nadir" in capsys.readouterr().err


def test_nadir_needs_a_value(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["semonitor.py", "-n"])

    with pytest.raises(SystemExit) as exit_:
        se.env.getArgs()

    assert exit_.value.code == 2


def test_nadir_is_off_by_default(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["semonitor.py"])

    assert se.env.getArgs()[0].nadir is None


# --- nextNadirEpoch ----------------------------------------------------------


def test_nadir_is_today_when_it_is_still_to_come(sm, local_zone):
    local_zone("UTC0")

    epoch = sm.nextNadirEpoch(
        datetime.time(1, 40), datetime.datetime(2026, 11, 13, 1, 0)
    )

    assert local(epoch) == datetime.datetime(2026, 11, 13, 1, 40)


def test_nadir_is_tomorrow_once_it_has_passed(sm, local_zone):
    local_zone("UTC0")

    epoch = sm.nextNadirEpoch(
        datetime.time(1, 40), datetime.datetime(2026, 11, 13, 2, 0)
    )

    assert local(epoch) == datetime.datetime(2026, 11, 14, 1, 40)


def test_nadir_exactly_now_is_tomorrow(sm, local_zone):
    local_zone("UTC0")

    epoch = sm.nextNadirEpoch(
        datetime.time(1, 40), datetime.datetime(2026, 11, 13, 1, 40)
    )

    assert local(epoch) == datetime.datetime(2026, 11, 14, 1, 40)


def test_nadir_is_the_next_calendar_day_across_a_dst_change(sm, local_zone):
    # the day the clocks go back is 25 hours long: tomorrow's nadir is at
    # 01:40 on the calendar, not 24 hours after today's
    local_zone(TZ_EUROPE)

    epoch = sm.nextNadirEpoch(
        datetime.time(1, 40), datetime.datetime(2026, 10, 24, 12, 0)
    )
    assert local(epoch) == datetime.datetime(2026, 10, 25, 1, 40)

    epoch = sm.nextNadirEpoch(
        datetime.time(1, 40), datetime.datetime(2026, 10, 25, 1, 40)
    )
    assert local(epoch) == datetime.datetime(2026, 10, 26, 1, 40)


# --- block -------------------------------------------------------------------


def test_block_exits_with_0_once_the_nadir_has_passed(
    sm, files, monkeypatch, caplog
):
    now = [FROZEN_TIME]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(
        sm, "time", SimpleNamespace(time=lambda: now[0], sleep=sleep)
    )
    monkeypatch.setattr(sm, "nadirEpoch", FROZEN_TIME + 3)

    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as exit_:
            sm.block(files.state)

    assert exit_.value.code == 0
    assert "Nadir reached, exiting" in caplog.text


def test_block_keeps_waiting_before_the_nadir(sm, files, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        sm, "time", SimpleNamespace(time=lambda: FROZEN_TIME, sleep=sleep)
    )
    monkeypatch.setattr(sm, "nadirEpoch", FROZEN_TIME + 3600)

    sm.block(files.state)

    assert sleeps == [1, 1]


def test_block_exits_with_0_on_the_end_of_day_event(
    sm, files, monkeypatch, caplog
):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        sm, "time", SimpleNamespace(time=lambda: FROZEN_TIME, sleep=sleep)
    )
    monkeypatch.setattr(sm, "eodEvent", True)

    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as exit_:
            sm.block(files.state)

    assert exit_.value.code == 0
    assert "Nadir event received, exiting" in caplog.text
    assert sleeps == []


# --- event mode --------------------------------------------------------------


def process(sm, msg, files, nadir, mode=MASTER_MODE):
    sm.processMsg(
        msg,
        make_args(nadir=nadir),
        mode,
        files.state,
        files.line,
        files.rec,
        files.out,
        files.update_buf,
    )


def test_event_mode_has_no_nadir_time(sm):
    assert sm.nadirEpoch is None
    assert sm.eodEvent is False


def test_end_of_day_event_is_seen_in_event_mode(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files, se.env.NADIR_EVENT)

    assert sm.eodEvent is True


def test_data_is_written_and_acknowledged_before_the_event_exits(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files, se.env.NADIR_EVENT)

    assert b"73124CBA" in files.out.getvalue()
    assert files.line.written  # the ack, in master mode
    assert sm.eodEvent is True


def test_wake_events_do_not_end_the_run(sm, files):
    messages = messages_with_event(WAKE_RECORDING, 1)
    assert messages

    for msg in messages:
        process(sm, msg, files, se.env.NADIR_EVENT)

    assert sm.eodEvent is False


def test_other_event_types_do_not_end_the_run(sm, files):
    # Type 114 is junk that shows up in the recordings
    for msg in messages_with_event(EOD_RECORDING, 114):
        process(sm, msg, files, se.env.NADIR_EVENT)

    assert sm.eodEvent is False


def test_end_of_day_event_is_ignored_without_event_mode(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files, None)

    assert sm.eodEvent is False


# --- end-to-end --------------------------------------------------------------


def test_event_mode_exits_0_right_after_the_end_of_day_event(
    run_semonitor, golden
):
    recording = golden("rec", EOD_RECORDING)

    plain = run_semonitor("-x", recording)
    result = run_semonitor("-x", "-n", "event", recording)

    assert result.returncode == 0
    assert plain.returncode == 0
    lines = result.stdout.splitlines()
    assert len(lines) == EOD_LINE
    assert lines == plain.stdout.splitlines()[:EOD_LINE]
    assert len(plain.stdout.splitlines()) > EOD_LINE


def test_event_mode_keeps_reading_without_an_end_of_day_event(
    run_semonitor, golden
):
    result = run_semonitor("-x", "-n", "event", golden("rec", WAKE_RECORDING))

    assert result.returncode == 0
    assert (
        result.stdout
        == run_semonitor("-x", golden("rec", WAKE_RECORDING)).stdout
    )
