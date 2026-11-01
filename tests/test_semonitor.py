import datetime as dt
import functools
import importlib.util
import io
import json
import logging
import struct
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial
import serial.tools.list_ports

import se.commands
import se.data
import se.env
import se.logutils
import se.msg

from .conftest import GOLDEN_DIR, SAMPLES

ROOT = Path(__file__).resolve().parent.parent
SEMONITOR = ROOT / "semonitor.py"

MAGIC = se.msg.magic
MASTER_ADDR = 0xFFFFFFFE
SLAVE = 0x7F000001
SLAVE_ARG = "7f000001"
DEVICE = "/dev/ttyFAKE"
FROZEN_TIME = 1_700_000_000  # 2023-11-14 22:13:20 UTC

ACK = se.commands.PROT_RESP_ACK
POST_DATA = se.commands.PROT_CMD_SERVER_POST_DATA
GET_GMT = se.commands.PROT_CMD_SERVER_GET_GMT
RESP_GMT = se.commands.PROT_RESP_SERVER_GMT
GRANT = se.commands.PROT_CMD_POLESTAR_MASTER_GRANT
GRANT_ACK = se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK
ENCRYPTED_DATA = 0x003D
ENCRYPTION_KEY = 0x0503
MASTER_ANSWERED_REQUESTS = (POST_DATA, GET_GMT, ENCRYPTION_KEY)

HEADER = struct.Struct("<HHHLLH")

# the recording with the end-of-day event (Type 0) of inverter 73124CBA, in
# its 7th performance data message
EOD_RECORDING = "oliv3r-20180218"
EOD_LINE = 7
# the recording with wake events (Type 1), and no end-of-day event
WAKE_RECORDING = "d-tamm-20160809"
TZ_EUROPE = "CET-1CEST,M3.5.0,M10.5.0/3"  # clocks go back on 2026-10-25


class StopLoopError(Exception):
    pass


class FakeLine:
    def __init__(self, incoming=b"", name="<fake>"):
        self.name = name
        self.incoming = io.BytesIO(incoming)
        self.written = bytearray()
        self.closed = False

    def read(self, size=-1):
        return self.incoming.read(size)

    def write(self, data):
        self.written += data
        return len(data)

    def flush(self):
        return None

    def close(self):
        self.closed = True


# A serial port never returns an empty read, it waits. The data ends like a
# device that is unplugged: the read raises.
class FakeSerialLine(FakeLine):
    def read(self, size=-1):
        data = super().read(size)
        if not data:
            msg = "device reports readiness to read but returned no data"
            raise serial.SerialException(msg)
        return data


class NamedBytesIO(io.BytesIO):
    name = "<stdin>"


class FakeTimer:
    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.canceled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.canceled = True


class FakeEvent:
    def __init__(self):
        self.flag = False
        self.waits = 0
        self.on_wait = None

    def set(self):
        self.flag = True

    def clear(self):
        self.flag = False

    def is_set(self):
        return self.flag

    def wait(self):
        self.waits += 1
        if self.on_wait:
            self.on_wait()


class NoWaitEvent(threading.Event):
    def wait(self, *_args, **_kwargs):
        return self.is_set()


def load_semonitor():
    spec = importlib.util.spec_from_file_location(
        "semonitor_under_test", SEMONITOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_mode(**changes):
    mode = {
        "serialDevice": False,
        "serialType": None,
        "passiveMode": True,
        "masterMode": False,
        "following": False,
    }
    return se.env.RunMode(**{**mode, **changes})


def make_args(**changes):
    args = {
        "xerror": False,
        "commands": [],
        "slaves": [],
        "nadir": None,
    }
    return SimpleNamespace(**{**args, **changes})


def make_files():
    return SimpleNamespace(
        line=FakeLine(),
        rec=io.BytesIO(),
        out=io.BytesIO(),
        state={},
    )


PASSIVE_MODE = make_mode()
# RS485 without taking part: the messages are not read like those of RS232.
LISTEN_MODE = make_mode(serialDevice=True, serialType="4", passiveMode=False)
MASTER_MODE = make_mode(
    serialDevice=True, serialType="4", passiveMode=False, masterMode=True
)
COMMAND_MODE = LISTEN_MODE


def frame(function, data=b"", seq=7, source=SLAVE, dest=MASTER_ADDR):
    return bytes(se.msg.format_msg(seq, source, dest, function, data))


def corrupt(msg):
    damaged = bytearray(msg)
    damaged[-1] ^= 0xFF
    return bytes(damaged)


@functools.cache
def recorded_messages(recording):
    data = (GOLDEN_DIR / "rec" / f"{recording}.rec").read_bytes()
    return tuple(data.split(MAGIC))


def fields(msg):
    (_, _, seq, source, dest, function) = HEADER.unpack(msg[: HEADER.size])
    return seq, source, dest, function


def function_of(msg):
    if len(msg) < HEADER.size:
        return None
    return fields(msg)[3]


def carries_data(msg):
    return len(se.msg.parse_msg(msg)[4]) > 0


def carries_no_data(msg):
    return not carries_data(msg)


def event_types(msg):
    # the types of the events in a performance data message
    data = se.msg.parse_msg(msg)[4]
    events = se.data.parse_data(POST_DATA, data)["events"]
    return {e.get("Type") for e in events.values()}


def messages_with_event(recording, wanted):
    return [
        msg
        for msg in recorded_messages(recording)
        if function_of(msg) == POST_DATA
        and carries_data(msg)
        and wanted in event_types(msg)
    ]


# A reply has the sequence number of its request, and the addresses swapped.
def answers(request, reply):
    if len(reply) < HEADER.size:
        return False
    (seq, source, dest, _) = fields(request)
    (reply_seq, reply_source, reply_dest, _) = fields(reply)
    return (reply_seq, reply_source, reply_dest) == (seq, dest, source)


def _index_of(recording, function, want):
    messages = recorded_messages(recording)
    for index, msg in enumerate(messages[:-1]):
        if function_of(msg) != function or not want(msg):
            continue
        if function in MASTER_ANSWERED_REQUESTS and not answers(
            msg, messages[index + 1]
        ):
            continue
        return index
    return None


# The first message of a function that passes want, and the message after it:
# the reply, for the requests that the master answers.
def recorded_exchange(recording, function, want=lambda _msg: True):
    index = _index_of(recording, function, want)
    if index is None:
        msg = f"{function:#06x} is not in {recording}"
        raise LookupError(msg)
    messages = recorded_messages(recording)
    return messages[index], messages[index + 1]


def first_exchanges(function, want=lambda _msg: True):
    return [
        (recording, *recorded_exchange(recording, function, want))
        for recording in SAMPLES
        if _index_of(recording, function, want) is not None
    ]


# The recording is only part of the arguments when the test needs it.
def cases(label, found, *, keep_recording=False):
    skip = 0 if keep_recording else 1
    return [
        pytest.param(*case[skip:], id=f"{label}-{case[0]}") for case in found
    ]


# A TZ string for an offset in seconds east of UTC.
def posix_zone(offset):
    sign = "-" if offset >= 0 else "+"
    hours, rest = divmod(abs(offset), 3600)
    return f"UTC{sign}{hours}:{rest // 60:02d}"


def first_json_line(golden, recording):
    path = golden("json", recording)
    return path.read_bytes().splitlines(keepends=True)[0]


def fake_time(now=FROZEN_TIME, sleep=None):
    return SimpleNamespace(
        time=lambda: now,
        localtime=lambda: time.localtime(now),
        gmtime=lambda: time.gmtime(now),
        sleep=sleep or (lambda _seconds: None),
    )


def set_zone(monkeypatch, zone):
    monkeypatch.setenv("TZ", zone)
    time.tzset()


# The UNIX epoch of a local date and time, given as year, month, day, hour
# and minute.
def local_epoch(*local_time):
    return time.mktime((*local_time, 0, 0, 0, -1))


# The local date and time of a UNIX epoch, as year, month, day, hour, minute.
def local_date_time(epoch):
    return time.localtime(epoch)[:5]


def fake_bus(sm, monkeypatch):
    bus = SimpleNamespace(timers=[], event=FakeEvent())

    def make_timer(interval, function):
        bus.timers.append(FakeTimer(interval, function))
        return bus.timers[-1]

    monkeypatch.setattr(threading, "Timer", make_timer)
    monkeypatch.setattr(sm, "master_event", bus.event)
    return bus


def process(sm, msg, files, mode=MASTER_MODE, **changes):
    sm.process_msg(
        msg,
        make_args(**changes),
        mode,
        files.state,
        sm.Files(files.line, files.rec, files.out),
    )


def read(sm, files, mode=PASSIVE_MODE, **changes):
    sm.read_data(
        make_args(**changes),
        mode,
        files.state,
        sm.Files(files.line, files.rec, files.out),
    )


def install_serial(monkeypatch, line):
    opened = []

    def open_port(name, baudrate):
        opened.append((name, baudrate))
        return line

    monkeypatch.setattr(serial, "Serial", open_port)
    monkeypatch.setattr(
        serial.tools.list_ports,
        "comports",
        lambda: [(DEVICE, "fake port", "n/a")],
    )
    return opened


def patch_threads(monkeypatch):
    threads = SimpleNamespace(real=[], stubbed=[])

    class SelectiveThread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.spec = kwargs

        def start(self):
            if self.name == "master thread":
                threads.stubbed.append(self)
            else:
                threads.real.append(self)
                super().start()

    monkeypatch.setattr(threading, "Thread", SelectiveThread)
    return threads


def join_threads(threads):
    for thread in threads.real:
        thread.join(timeout=5)
        assert not thread.is_alive()


def interrupt_on_sleep(monkeypatch, threads):

    def sleep(_seconds):
        join_threads(threads)
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", sleep)


@pytest.fixture
def sm():
    return load_semonitor()


@pytest.fixture
def files():
    return make_files()


# --- -n argument -------------------------------------------------------------


@pytest.fixture
def get_nadir(monkeypatch):

    def run(value):
        monkeypatch.setattr(sys, "argv", ["semonitor.py", "-n", value])
        return se.env.get_args()[0].nadir

    return run


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("default", dt.time(1, 40)),
        ("DEFAULT", dt.time(1, 40)),
        ("0:00", dt.time(0, 0)),
        ("04:05", dt.time(4, 5)),
        ("23:59", dt.time(23, 59)),
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
        se.env.get_args()

    assert exit_.value.code == 2


def test_nadir_is_off_by_default(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["semonitor.py"])

    assert se.env.get_args()[0].nadir is None


# --- terminate ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "level", "msg"),
    [(0, logging.INFO, "all done"), (3, logging.ERROR, "it broke")],
)
def test_terminate_exits_and_logs_the_reason(sm, caplog, code, level, msg):
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exit_:
        sm.terminate(code, msg)

    assert exit_.value.code == code
    assert caplog.record_tuples == [("semonitor_under_test", level, msg)]


def test_terminate_defaults_to_success(sm):
    with pytest.raises(SystemExit) as exit_:
        sm.terminate()

    assert exit_.value.code == 0


# --- process_msg --------------------------------------------------------------


# Synthetic: no recording has a message that is too short, or function 0.
# The damaged message is a real one with its checksum spoiled.
@pytest.mark.parametrize(
    "msg",
    [
        pytest.param(b"too short", id="too-short"),
        pytest.param(frame(0, b"\x01" * 20), id="function-0"),
        *[
            pytest.param(corrupt(req), id=f"bad-checksum-{recording}")
            for recording, req, _ in first_exchanges(POST_DATA)
        ],
    ],
)
def test_message_without_function_is_ignored(sm, files, caplog, msg):
    with caplog.at_level(se.logutils.LOG_LEVEL_DATA):
        process(sm, msg, files)

    assert "Ignoring this message" in caplog.text
    assert not files.line.written
    assert not files.out.getvalue()


@pytest.mark.parametrize(
    ("recording", "req", "_reply"),
    cases(
        "performance-data",
        first_exchanges(POST_DATA, carries_data),
        keep_recording=True,
    ),
)
def test_performance_data_is_written_as_json(
    sm, files, golden, recording, req, _reply
):
    process(sm, req, files, PASSIVE_MODE)

    assert files.out.getvalue() == first_json_line(golden, recording)


@pytest.mark.parametrize(
    ("req", "_reply"),
    cases("no-performance-data", first_exchanges(POST_DATA, carries_no_data)),
)
def test_no_performance_data_means_nothing_is_written(sm, files, req, _reply):
    process(sm, req, files, PASSIVE_MODE)

    assert not files.out.getvalue()


@pytest.mark.parametrize(
    ("req", "ack"),
    cases("post-data", first_exchanges(POST_DATA))
    + cases("encryption-key", first_exchanges(ENCRYPTION_KEY)),
)
def test_data_and_keys_are_acknowledged(sm, files, req, ack):
    process(sm, req, files)

    assert bytes(files.line.written) == MAGIC + ack
    assert files.rec.getvalue() == MAGIC + ack


@pytest.mark.parametrize(
    ("req", "reply"),
    cases("time-request", first_exchanges(GET_GMT)),
)
def test_time_request_is_answered_like_the_real_master_did(
    sm, files, monkeypatch, req, reply
):
    (stamp, offset) = struct.unpack("<Ll", reply[HEADER.size :][:8])
    set_zone(monkeypatch, posix_zone(offset))
    monkeypatch.setattr(sm, "time", fake_time(stamp))

    process(sm, req, files)

    assert bytes(files.line.written) == MAGIC + reply
    assert files.rec.getvalue() == MAGIC + reply


# Synthetic: FROZEN_TIME is 22:13 UTC, so zones far enough ahead of UTC
# are on the next date.
@pytest.mark.parametrize(
    ("zone", "offset"),
    [
        pytest.param("UTC0", 0, id="utc"),
        pytest.param("EST5", -5 * 3600, id="behind-utc"),
        pytest.param("CET-1", 3600, id="ahead-of-utc"),
        pytest.param(
            "EET-2",
            2 * 3600,
            id="ahead-of-utc-past-midnight",
            marks=pytest.mark.xfail(strict=True, reason="Issue #11"),
        ),
        pytest.param(
            "IST-5:30",
            (5 * 3600) + (30 * 60),
            id="half-hour-zone",
            marks=pytest.mark.xfail(strict=True, reason="Issue #11"),
        ),
    ],
)
def test_time_reply_has_the_offset_of_the_zone(
    sm, files, monkeypatch, zone, offset
):
    set_zone(monkeypatch, zone)
    monkeypatch.setattr(sm, "time", fake_time(FROZEN_TIME))

    process(sm, frame(GET_GMT, seq=5), files)

    reply = frame(
        RESP_GMT,
        struct.pack("<Ll", FROZEN_TIME, offset),
        seq=5,
        source=MASTER_ADDR,
        dest=SLAVE,
    )
    assert bytes(files.line.written) == MAGIC + reply


@pytest.mark.parametrize(
    ("req", "_reply"),
    cases("master-grant-ack", first_exchanges(GRANT_ACK)),
)
def test_master_grant_ack_releases_the_bus(sm, files, req, _reply):
    process(sm, req, files)

    assert sm.master_event.is_set()
    assert files.state["masterEvent"][1] is True
    assert not files.line.written


@pytest.mark.xfail(strict=True, reason="Issue #13")
def test_master_grant_ack_with_data_releases_the_bus(sm, files):
    process(sm, frame(GRANT_ACK, b"\x01\x02"), files)

    assert sm.master_event.is_set()


@pytest.mark.parametrize(
    ("req", "_reply"),
    cases("post-data", first_exchanges(POST_DATA))
    + cases("time-request", first_exchanges(GET_GMT))
    + cases("encryption-key", first_exchanges(ENCRYPTION_KEY))
    + cases("master-grant-ack", first_exchanges(GRANT_ACK)),
)
def test_passive_mode_never_replies(sm, files, req, _reply):
    process(sm, req, files, PASSIVE_MODE)

    assert not files.line.written
    assert not files.rec.getvalue()
    assert not sm.master_event.is_set()


@pytest.mark.parametrize(
    ("req", "_reply"),
    cases("encrypted-data", first_exchanges(ENCRYPTED_DATA))
    + cases("master-grant", first_exchanges(GRANT))
    + cases("acknowledgment", first_exchanges(ACK)),
)
def test_other_functions_are_not_answered(sm, files, req, _reply):
    process(sm, req, files)

    assert not files.line.written
    assert not sm.master_event.is_set()


# --- process_msg: end-of-day event --------------------------------------------


def test_event_mode_starts_without_an_end_of_day_event(sm):
    assert not sm.eod_event.is_set()


def test_end_of_day_event_is_seen_in_event_mode(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files, nadir=se.env.NADIR_EVENT)

    assert sm.eod_event.is_set()


def test_data_is_written_and_acknowledged_before_the_event_exits(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files, nadir=se.env.NADIR_EVENT)

    assert b"73124CBA" in files.out.getvalue()
    assert files.line.written  # the ack, in master mode
    assert sm.eod_event.is_set()


def test_wake_events_do_not_end_the_run(sm, files):
    messages = messages_with_event(WAKE_RECORDING, 1)
    assert messages

    for msg in messages:
        process(sm, msg, files, nadir=se.env.NADIR_EVENT)

    assert not sm.eod_event.is_set()


def test_other_event_types_do_not_end_the_run(sm, files):
    # Type 114 is junk that shows up in the recordings
    for msg in messages_with_event(EOD_RECORDING, 114):
        process(sm, msg, files, nadir=se.env.NADIR_EVENT)

    assert not sm.eod_event.is_set()


def test_end_of_day_event_is_ignored_without_event_mode(sm, files):
    eod = messages_with_event(EOD_RECORDING, 0)[0]

    process(sm, eod, files)

    assert not sm.eod_event.is_set()


# --- read_data ----------------------------------------------------------------


@pytest.fixture
def partial_first(files, golden, sample):
    """Feed the recording, with the first message cut short, to the line."""
    rec = golden("rec", sample).read_bytes()
    partial = recorded_messages(sample)[1][5:]
    files.line = FakeLine(partial + rec)
    return golden("json", sample).read_bytes()


@pytest.mark.parametrize(
    ("sample", "mode"),
    [
        pytest.param(
            sample,
            mode,
            id=f"{sample}-{name}",
            marks=pytest.mark.xfail(strict=True, reason="Issue #41"),
        )
        if (sample, name) == ("7f104920", "passive")
        else pytest.param(sample, mode, id=f"{sample}-{name}")
        for sample in SAMPLES
        for name, mode in (
            ("passive", PASSIVE_MODE),
            ("not-passive", LISTEN_MODE),
        )
    ],
)
def test_first_partial_message_is_skipped_in_passive_mode(
    sm, files, caplog, partial_first, mode
):
    with caplog.at_level(se.logutils.LOG_LEVEL_DATA):
        read(sm, files, mode)

    assert files.out.getvalue() == partial_first
    # A bus that is only listened to is not joined halfway: the partial
    # message is read, and found to be nothing.
    assert ("Ignoring this message" in caplog.text) is (mode == LISTEN_MODE)
    assert not files.line.written
    assert not sm.thread_lock.locked()


@pytest.mark.parametrize(
    ("stream", "logged"),
    [
        pytest.param(b"", False, id="empty"),
        pytest.param(b"x" + MAGIC + b"y", True, id="data"),
    ],
)
def test_end_of_file_ends_the_reading(sm, files, caplog, stream, logged):
    files.line = FakeLine(stream)

    with caplog.at_level(logging.INFO):
        read(sm, files)

    assert ("End of file" in caplog.text) is logged
    assert not files.out.getvalue()


def test_messages_of_zeros_or_nothing_are_ignored(
    sm, files, monkeypatch, sample
):
    seen = []
    monkeypatch.setattr(sm, "process_msg", lambda msg, *_rest: seen.append(msg))
    good, _ = recorded_exchange(sample, POST_DATA, carries_data)
    files.line = FakeLine(
        b"x" + MAGIC + MAGIC + bytes(8) + MAGIC + good + MAGIC + b"\x00\x01"
    )

    read(sm, files)

    assert seen == [good, b"\x00\x01"]


def test_message_that_fails_to_parse_is_logged_and_skipped(
    sm, files, caplog, golden, sample
):
    broken = frame(POST_DATA, b"\x00\x01")
    good, _ = recorded_exchange(sample, POST_DATA, carries_data)
    files.line = FakeLine(b"x" + MAGIC + broken + MAGIC + good)

    with caplog.at_level(logging.INFO):
        read(sm, files)

    assert "Failed to parse message" in caplog.text
    assert files.out.getvalue() == first_json_line(golden, sample)
    assert not sm.thread_lock.locked()
    assert files.state["threadLock"][1] is False


def test_message_that_fails_to_parse_stops_the_reading_with_x(
    sm, files, sample
):
    good, _ = recorded_exchange(sample, POST_DATA, carries_data)
    files.line = FakeLine(
        b"x" + MAGIC + frame(POST_DATA, b"\x00\x01") + MAGIC + good
    )

    with pytest.raises(struct.error):
        read(sm, files, xerror=True)

    assert not files.out.getvalue()
    assert not sm.thread_lock.locked()


# --- master_grant -------------------------------------------------------------


@pytest.mark.parametrize(
    ("grant", "_reply"),
    cases("master-grant", first_exchanges(GRANT)),
)
def test_master_grant_sends_the_grant_of_the_real_master(
    sm, files, monkeypatch, grant, _reply
):
    fake_bus(sm, monkeypatch)  # or the real 10 second timeout is waited for
    seq, _, dest, _ = fields(grant)
    slave_arg = f"{dest:08x}"
    Path(sm.SEQ_FILE_NAME).write_text(f"{seq - 1}\n")

    sm.master_grant(files.state, files.line, files.rec, slave_arg)

    assert bytes(files.line.written) == MAGIC + grant
    assert files.rec.getvalue() == MAGIC + grant
    assert Path(sm.SEQ_FILE_NAME).read_text() == f"{seq}\n"


def test_master_grant_hands_over_the_bus_until_the_slave_releases_it(
    sm, files, monkeypatch
):
    bus = fake_bus(sm, monkeypatch)
    lock_held = {"write": [], "wait": []}
    write = files.line.write

    def probe_write(data):
        lock_held["write"].append(sm.thread_lock.locked())
        return write(data)

    def slave_releases_the_bus():
        lock_held["wait"].append(sm.thread_lock.locked())
        bus.event.set()

    monkeypatch.setattr(files.line, "write", probe_write)
    bus.event.on_wait = slave_releases_the_bus

    sm.master_grant(files.state, files.line, files.rec, SLAVE_ARG)

    grant = MAGIC + frame(GRANT, seq=1, source=MASTER_ADDR, dest=SLAVE)
    assert bytes(files.line.written) == grant
    assert files.rec.getvalue() == grant
    # The grant is sent under the lock, but the reply must be able to come in.
    assert lock_held == {"write": [True], "wait": [False]}
    (timer,) = bus.timers
    assert timer.interval == sm.MASTER_MSG_TIMEOUT
    assert timer.started
    assert timer.canceled
    assert bus.event.waits == 1
    assert files.state["masterTimer"][1] is False
    assert files.state["masterEvent"][1] is True


def test_master_grant_releases_the_bus_when_the_slave_is_silent(
    sm, files, monkeypatch, caplog
):
    bus = fake_bus(sm, monkeypatch)

    def timeout():
        bus.timers[0].function()

    bus.event.on_wait = timeout

    with caplog.at_level(logging.DEBUG):
        sm.master_grant(files.state, files.line, files.rec, SLAVE_ARG)

    assert "RS485 master ack timeout" in caplog.text
    assert bus.event.is_set()
    assert bus.timers[0].canceled
    assert files.state["masterTimer"][1] is False


# --- master_commands ----------------------------------------------------------


def test_master_commands_grant_all_slaves_over_and_over(sm, files, monkeypatch):
    granted = []
    sleeps = []

    def grant(state, line, rec, slave):
        granted.append((state, line, rec, slave))

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoopError

    monkeypatch.setattr(sm, "master_grant", grant)
    monkeypatch.setattr(sm, "time", fake_time(sleep=sleep))

    slaves = ["a1", "b2"]

    with pytest.raises(StopLoopError):
        sm.master_commands(files.state, files.line, files.rec, slaves)

    assert granted == [
        (files.state, files.line, files.rec, slave) for slave in slaves * 2
    ]
    assert sleeps == [sm.MASTER_MSG_INTERVAL] * 2
    assert files.state["masterThread"][1] is True


# --- do_commands --------------------------------------------------------------


COMMANDS = [["1f", "h1234", "l01020304", "b07"], ["20"]]


def _recordings_with(function):
    return {recording for recording, _, _ in first_exchanges(function)}


# Send COMMANDS to a slave that answers them, with no delay. The answers are
# real messages: an acknowledgment, then a time. Only recordings that have
# both are used.
COMMAND_RECORDINGS = [
    recording
    for recording in SAMPLES
    if recording in _recordings_with(POST_DATA)
    and recording in _recordings_with(GET_GMT)
]


@pytest.fixture(params=COMMAND_RECORDINGS)
def command_recording(request):
    return request.param


@pytest.fixture
def command_run(sm, files, monkeypatch, command_recording):
    sleeps = []
    monkeypatch.setattr(sm, "time", fake_time(sleep=sleeps.append))
    (_, ack) = recorded_exchange(command_recording, POST_DATA)
    (_, time_reply) = recorded_exchange(command_recording, GET_GMT)
    files.line = FakeLine(ack + MAGIC + time_reply + MAGIC)
    return SimpleNamespace(sleeps=sleeps, time_reply=time_reply)


def sent_commands():
    first = struct.pack("<hlb", 0x1234, 0x01020304, 7)
    return [
        MAGIC + frame(function, data, seq=seq, source=MASTER_ADDR, dest=SLAVE)
        for seq, function, data in ((1, 0x1F, first), (2, 0x20, b""))
    ]


def test_commands_are_sent_and_their_responses_written(sm, files, command_run):
    args = make_args(commands=COMMANDS, slaves=[SLAVE_ARG])

    sm.do_commands(
        args,
        COMMAND_MODE,
        files.state,
        sm.Files(files.line, files.rec, files.out),
    )

    assert bytes(files.line.written) == b"".join(sent_commands())
    assert files.rec.getvalue().startswith(sent_commands()[0])
    (stamp, offset) = struct.unpack(
        "<Ll", command_run.time_reply[HEADER.size :][:8]
    )
    written = [json.loads(line) for line in files.out.getvalue().splitlines()]
    assert written == [
        {"command": 0x1F, "data": "", "response": ACK, "sequence": 1},
        {
            "command": 0x20,
            "data": {"time": stamp, "tz": offset},
            "response": RESP_GMT,
            "sequence": 2,
        },
    ]
    assert command_run.sleeps == [sm.COMMAND_DELAY] * 2
    assert Path(sm.SEQ_FILE_NAME).read_text() == "2\n"


@pytest.mark.usefixtures("command_run")
def test_unsigned_parameters_of_a_command_are_sent_unsigned(sm, files):
    args = make_args(commands=[["1f", "HFFFF", "LFFFFFFFF"]], slaves=["7f"])

    sm.do_commands(
        args,
        COMMAND_MODE,
        files.state,
        sm.Files(files.line, files.rec, files.out),
    )

    sent = frame(
        0x1F,
        struct.pack("<HL", 0xFFFF, 0xFFFFFFFF),
        seq=1,
        source=MASTER_ADDR,
        dest=0x7F,
    )
    assert bytes(files.line.written) == MAGIC + sent


def test_master_gives_the_bus_to_the_slave_after_each_command(
    sm, files, command_run, monkeypatch
):
    sent_when_granted = []

    def grant(_state, line, _rec, slave):
        sent_when_granted.append((len(line.written), slave))

    monkeypatch.setattr(sm, "master_grant", grant)
    args = make_args(commands=COMMANDS, slaves=[SLAVE_ARG, "ignored"])

    sm.do_commands(
        args,
        MASTER_MODE,
        files.state,
        sm.Files(files.line, files.rec, files.out),
    )

    first_length = len(sent_commands()[0])
    assert sent_when_granted == [
        (first_length, SLAVE_ARG),
        (len(b"".join(sent_commands())), SLAVE_ARG),
    ]
    assert command_run.sleeps == [sm.COMMAND_DELAY] * 2


# --- start_master -------------------------------------------------------------


def test_start_master_starts_a_daemon_thread(sm, files, monkeypatch, caplog):
    created = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.daemon = False
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(threading, "Thread", FakeThread)
    args = (files.state, files.line, files.rec, ["a1"])

    with caplog.at_level(logging.INFO):
        sm.start_master(args)

    (thread,) = created
    assert thread.kwargs == {
        "name": "master thread",
        "target": sm.master_commands,
        "args": args,
    }
    assert thread.daemon
    assert thread.started
    assert "starting master thread" in caplog.text


# --- block -------------------------------------------------------------------


def test_block_dumps_the_state_on_a_keyboard_interrupt(
    sm, files, monkeypatch, caplog
):
    sleeps = []

    def interrupt(seconds):
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(sm, "time", fake_time(sleep=interrupt))
    files.state["readThread"] = [FROZEN_TIME, True]

    with caplog.at_level(logging.INFO):
        sm.block(files.state)

    assert sleeps == [1]
    assert "state:" in caplog.text
    assert "readThread: True" in caplog.text


def test_block_keeps_waiting_until_it_is_interrupted(sm, files, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(sm, "time", fake_time(sleep=sleep))

    sm.block(files.state)

    assert sleeps == [1, 1, 1]


def test_block_exits_with_0_once_the_nadir_has_passed(
    sm, files, monkeypatch, caplog
):
    now = [FROZEN_TIME]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(
        sm, "time", SimpleNamespace(time=lambda: now[0], sleep=sleep)
    )
    nadir_epoch = FROZEN_TIME + 3

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exit_:
        sm.block(files.state, nadir_epoch)

    assert exit_.value.code == 0
    assert "Nadir reached, exiting" in caplog.text


def test_block_keeps_waiting_before_the_nadir(sm, files, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(sm, "time", fake_time(sleep=sleep))

    sm.block(files.state, FROZEN_TIME + 3600)

    assert sleeps == [1, 1]


def test_block_exits_with_0_on_the_end_of_day_event(
    sm, files, monkeypatch, caplog
):
    sleeps = []
    monkeypatch.setattr(sm, "time", fake_time(sleep=sleeps.append))
    sm.eod_event.set()

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exit_:
        sm.block(files.state)

    assert exit_.value.code == 0
    assert "Nadir event received, exiting" in caplog.text
    assert sleeps == []


# --- next_seq -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        pytest.param(None, 1, id="no-file"),
        pytest.param("41\n", 42, id="increments"),
        pytest.param("9", 10, id="no-newline"),
        pytest.param("65534\n", 65535, id="last"),
        pytest.param("65535\n", 1, id="wraps-around"),
    ],
)
def test_next_sequence_number(sm, stored, expected):
    if stored is not None:
        Path(sm.SEQ_FILE_NAME).write_text(stored)

    assert sm.next_seq() == expected
    assert Path(sm.SEQ_FILE_NAME).read_text() == f"{expected}\n"


def test_sequence_numbers_keep_counting(sm):
    assert [sm.next_seq() for _ in range(3)] == [1, 2, 3]


def test_next_sequence_number_fails_when_it_can_not_be_saved(sm):
    Path(sm.SEQ_FILE_NAME).mkdir()

    with pytest.raises(OSError, match=r"seseq\.txt"):
        sm.next_seq()


@pytest.mark.xfail(strict=True, reason="Issue #14")
@pytest.mark.parametrize("stored", ["garbage\n", ""])
def test_next_sequence_number_restarts_after_a_damaged_file(sm, stored):
    Path(sm.SEQ_FILE_NAME).write_text(stored)

    assert sm.next_seq() == 1
    assert Path(sm.SEQ_FILE_NAME).read_text() == "1\n"


# --- next_nadir_epoch --------------------------------------------------------


def test_nadir_is_today_when_it_is_still_to_come(sm):
    epoch = sm.next_nadir_epoch(dt.time(1, 40), local_epoch(2026, 11, 13, 1, 0))

    assert local_date_time(epoch) == (2026, 11, 13, 1, 40)


def test_nadir_is_tomorrow_once_it_has_passed(sm):
    epoch = sm.next_nadir_epoch(dt.time(1, 40), local_epoch(2026, 11, 13, 2, 0))

    assert local_date_time(epoch) == (2026, 11, 14, 1, 40)


def test_nadir_exactly_now_is_tomorrow(sm):
    epoch = sm.next_nadir_epoch(
        dt.time(1, 40), local_epoch(2026, 11, 13, 1, 40)
    )

    assert local_date_time(epoch) == (2026, 11, 14, 1, 40)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param((2026, 12, 31, 2, 0), (2027, 1, 1, 1, 40), id="year-end"),
        pytest.param((2028, 2, 28, 2, 0), (2028, 2, 29, 1, 40), id="leap-day"),
    ],
)
def test_nadir_tomorrow_can_be_in_the_next_month_or_year(sm, now, expected):
    epoch = sm.next_nadir_epoch(dt.time(1, 40), local_epoch(*now))

    assert local_date_time(epoch) == expected


def test_nadir_is_the_next_calendar_day_across_a_dst_change(sm, monkeypatch):
    # the day the clocks go back is 25 hours long: tomorrow's nadir is at
    # 01:40 on the calendar, not 24 hours after today's
    set_zone(monkeypatch, TZ_EUROPE)

    epoch = sm.next_nadir_epoch(
        dt.time(1, 40), local_epoch(2026, 10, 24, 12, 0)
    )
    assert local_date_time(epoch) == (2026, 10, 25, 1, 40)

    epoch = sm.next_nadir_epoch(
        dt.time(1, 40), local_epoch(2026, 10, 25, 1, 40)
    )
    assert local_date_time(epoch) == (2026, 10, 26, 1, 40)


def test_nadir_defaults_to_the_current_time(sm, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: local_epoch(2026, 11, 13, 1, 0))

    epoch = sm.next_nadir_epoch(dt.time(1, 40))

    assert local_date_time(epoch) == (2026, 11, 13, 1, 40)


# --- program as a whole ------------------------------------------------------


@pytest.mark.parametrize("source", [["-"], ["stdin"], []])
def test_stdin_is_read_when_there_is_no_file(
    run_semonitor, golden, monkeypatch, source, sample
):
    rec = golden("rec", sample).read_bytes()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(NamedBytesIO(rec)))

    result = run_semonitor("-x", *source)

    assert result.returncode == 0
    assert result.stdout == golden("json", sample).read_bytes()


def test_file_is_read_and_the_json_goes_to_a_file(
    run_semonitor, golden, sample
):
    result = run_semonitor("-x", "-o", "out.json", golden("rec", sample))

    assert result.returncode == 0
    assert result.stdout == b""
    assert Path("out.json").read_bytes() == golden("json", sample).read_bytes()


def test_serial_device_is_only_listened_to_in_passive_mode(
    run_semonitor, golden, monkeypatch, sample
):
    line = FakeSerialLine(golden("rec", sample).read_bytes(), DEVICE)
    opened = install_serial(monkeypatch, line)

    result = run_semonitor(
        "-t", "4", "-b", "9600", "-r", "in.rec", "-o", "out.json", DEVICE
    )

    assert result.returncode == 0
    assert opened == [(DEVICE, 9600)]
    assert result.stdout == b""
    assert Path("out.json").read_bytes() == golden("json", sample).read_bytes()
    assert Path("in.rec").read_bytes() == golden("rec", sample).read_bytes()
    assert not line.written
    assert line.closed


def test_serial_device_output_is_appended_with_option_a(
    run_semonitor, golden, monkeypatch, sample
):
    rec = golden("rec", sample).read_bytes()
    install_serial(monkeypatch, FakeSerialLine(rec, DEVICE))
    args = ("-t", "4", "-r", "in.rec", "-o", "out.json", DEVICE)
    assert run_semonitor(*args).returncode == 0
    install_serial(monkeypatch, FakeSerialLine(rec, DEVICE))

    assert run_semonitor("-a", *args).returncode == 0

    expected = golden("json", sample).read_bytes()
    assert Path("out.json").read_bytes() == expected * 2
    assert Path("in.rec").read_bytes() == rec * 2


@pytest.mark.xfail(strict=True, reason="Issue #12")
def test_rs232_device_is_read_by_a_thread_while_the_program_waits(
    run_semonitor, golden, monkeypatch, sample
):
    line = FakeSerialLine(golden("rec", sample).read_bytes(), DEVICE)
    install_serial(monkeypatch, line)
    threads = patch_threads(monkeypatch)
    interrupt_on_sleep(monkeypatch, threads)

    result = run_semonitor("-v", "-t", "2", DEVICE)

    assert result.returncode == 0
    assert result.stdout == golden("json", sample).read_bytes()
    (reader,) = threads.real
    assert reader.name == "read thread"
    assert not threads.stubbed
    assert "starting read thread" in result.stderr
    assert "state:" in result.stderr
    assert not line.written
    assert line.closed


def test_command_mode_sends_the_commands_and_writes_the_responses(
    run_semonitor, monkeypatch, sample
):
    (_, ack) = recorded_exchange(sample, POST_DATA)
    line = FakeSerialLine(ack + MAGIC, DEVICE)
    install_serial(monkeypatch, line)
    delays = []
    monkeypatch.setattr(time, "sleep", delays.append)

    result = run_semonitor(
        "-t", "4", "-s", SLAVE_ARG, "-c", "1f,h1234", "-o", "out.json", DEVICE
    )

    assert result.returncode == 0
    sent = frame(
        0x1F, struct.pack("<h", 0x1234), seq=1, source=MASTER_ADDR, dest=SLAVE
    )
    assert bytes(line.written) == MAGIC + sent
    assert json.loads(Path("out.json").read_bytes()) == {
        "command": 0x1F,
        "data": "",
        "response": ACK,
        "sequence": 1,
    }
    assert delays == [2]
    assert line.closed


def test_command_mode_as_master_grants_the_bus_after_each_command(
    run_semonitor, monkeypatch, sample
):
    (_, ack) = recorded_exchange(sample, POST_DATA)
    line = FakeSerialLine(ack + MAGIC, DEVICE)
    install_serial(monkeypatch, line)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    timers = []

    def make_timer(interval, function):
        timers.append(FakeTimer(interval, function))
        return timers[-1]

    # Nothing answers the grant, so waiting for it must not block.
    monkeypatch.setattr(threading, "Timer", make_timer)
    monkeypatch.setattr(threading, "Event", NoWaitEvent)

    result = run_semonitor(
        "-t", "4", "-m", "-s", SLAVE_ARG, "-c", "1f", "-o", "out.json", DEVICE
    )

    assert result.returncode == 0
    command = frame(0x1F, seq=1, source=MASTER_ADDR, dest=SLAVE)
    grant = frame(GRANT, seq=2, source=MASTER_ADDR, dest=SLAVE)
    assert bytes(line.written) == MAGIC + command + MAGIC + grant
    (timer,) = timers
    assert (timer.interval, timer.started, timer.canceled) == (10, True, True)
    assert line.closed


def test_master_mode_answers_the_traffic_of_a_real_master(
    run_semonitor, golden, monkeypatch, sample
):
    (request, _) = recorded_exchange(sample, POST_DATA)
    slave_arg = f"{fields(request)[1]:08x}"
    rec = golden("rec", sample).read_bytes()
    line = FakeSerialLine(rec, DEVICE)
    install_serial(monkeypatch, line)
    threads = patch_threads(monkeypatch)
    interrupt_on_sleep(monkeypatch, threads)
    before = int(time.time())

    result = run_semonitor(
        "-v", "-t", "4", "-m", "-s", slave_arg, "-o", "out.json", DEVICE
    )

    after = int(time.time())
    assert result.returncode == 0
    requests = [
        msg
        for msg in recorded_messages(sample)
        if function_of(msg) in (POST_DATA, GET_GMT, ENCRYPTION_KEY)
    ]
    replies = [msg for msg in bytes(line.written).split(MAGIC) if msg]
    assert len(replies) == len(requests)
    assert Path("out.json").read_bytes() == golden("json", sample).read_bytes()
    for request, reply in zip(requests, replies, strict=True):
        (seq, source, dest, function) = fields(request)
        if function in (POST_DATA, ENCRYPTION_KEY):
            assert reply == frame(ACK, seq=seq, source=dest, dest=source)
        else:
            (stamp, offset) = struct.unpack("<Ll", reply[HEADER.size :][:8])
            assert reply == frame(
                RESP_GMT,
                struct.pack("<Ll", stamp, offset),
                seq=seq,
                source=dest,
                dest=source,
            )
            assert before <= stamp <= after
            assert offset == 0
    (reader,) = threads.real
    assert reader.name == "read thread"
    assert reader.daemon
    (master,) = threads.stubbed
    assert master.daemon
    assert master.spec["name"] == "master thread"
    assert master.spec["target"].__name__ == "master_commands"
    (state, master_line, _, slaves) = master.spec["args"]
    assert master_line is line
    assert slaves == [slave_arg]
    assert "masterEvent" in state
    expected = [
        "starting read thread",
        "starting master thread",
        "closing out.json",
    ]
    # The bus is only released where the master sent a grant ack to release it.
    if any(function_of(msg) == GRANT_ACK for msg in recorded_messages(sample)):
        expected.append("masterEvent: True")
    for text in expected:
        assert text in result.stderr
    assert line.closed


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
