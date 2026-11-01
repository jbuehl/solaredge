import functools
import importlib.util
import io
import json
import logging
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest
import serial
import serial.tools.list_ports

import se.commands
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
UPGRADE_WRITE = se.commands.PROT_CMD_UPGRADE_WRITE
ENCRYPTED_DATA = 0x003D
ENCRYPTION_KEY = 0x0503
MASTER_ANSWERED_REQUESTS = (POST_DATA, GET_GMT, ENCRYPTION_KEY)

HEADER = struct.Struct("<HHHLLH")


class StopLoop(Exception):
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
            raise serial.SerialException(
                "device reports readiness to read but returned no data"
            )
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
    def wait(self, timeout=None):
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
        "updatefile": None,
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
        update_buf=[],
    )


PASSIVE_MODE = make_mode()
# RS485 without taking part: the messages are not read like those of RS232.
LISTEN_MODE = make_mode(serialDevice=True, serialType="4", passiveMode=False)
MASTER_MODE = make_mode(
    serialDevice=True, serialType="4", passiveMode=False, masterMode=True
)
COMMAND_MODE = LISTEN_MODE


def frame(function, data=b"", seq=7, source=SLAVE, dest=MASTER_ADDR):
    return bytes(se.msg.formatMsg(seq, source, dest, function, data))


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
    return len(se.msg.parseMsg(msg)[4]) > 0


def carries_no_data(msg):
    return not carries_data(msg)


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
def recorded_exchange(recording, function, want=lambda msg: True):
    index = _index_of(recording, function, want)
    if index is None:
        raise LookupError(f"{function:#06x} is not in {recording}")
    messages = recorded_messages(recording)
    return messages[index], messages[index + 1]


def first_exchanges(function, want=lambda msg: True):
    return [
        (recording, *recorded_exchange(recording, function, want))
        for recording in SAMPLES
        if _index_of(recording, function, want) is not None
    ]


# The recording is only part of the arguments when the test needs it.
def cases(label, found, keep_recording=False):
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
        sleep=sleep or (lambda _: None),
    )


def set_zone(monkeypatch, zone):
    monkeypatch.setenv("TZ", zone)
    time.tzset()


def fake_bus(sm, monkeypatch):
    bus = SimpleNamespace(timers=[], event=FakeEvent())

    def make_timer(interval, function):
        bus.timers.append(FakeTimer(interval, function))
        return bus.timers[-1]

    monkeypatch.setattr(threading, "Timer", make_timer)
    monkeypatch.setattr(sm, "masterEvent", bus.event)
    return bus


def process(sm, msg, files, mode=MASTER_MODE):
    sm.processMsg(
        msg,
        make_args(),
        mode,
        files.state,
        files.line,
        files.rec,
        files.out,
        files.update_buf,
    )


def read(sm, files, mode=PASSIVE_MODE, **changes):
    sm.readData(
        make_args(**changes),
        mode,
        files.state,
        files.line,
        files.rec,
        files.out,
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

    def sleep(_):
        join_threads(threads)
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", sleep)


@pytest.fixture
def sm():
    return load_semonitor()


@pytest.fixture
def files():
    return make_files()


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


# --- processMsg --------------------------------------------------------------


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
    ("recording", "req", "_"),
    cases(
        "performance-data",
        first_exchanges(POST_DATA, carries_data),
        keep_recording=True,
    ),
)
def test_performance_data_is_written_as_json(
    sm, files, golden, recording, req, _
):
    process(sm, req, files, PASSIVE_MODE)

    assert files.out.getvalue() == first_json_line(golden, recording)


@pytest.mark.parametrize(
    ("req", "_"),
    cases("no-performance-data", first_exchanges(POST_DATA, carries_no_data)),
)
def test_no_performance_data_means_nothing_is_written(sm, files, req, _):
    process(sm, req, files, PASSIVE_MODE)

    assert not files.out.getvalue()


def test_firmware_update_chunks_are_collected(sm, files):
    chunk = bytes(range(1, 9))
    data = struct.pack("<LL", 4, len(chunk)) + chunk
    files.update_buf = list(bytes(16))

    process(sm, frame(UPGRADE_WRITE, data), files, PASSIVE_MODE)

    assert files.update_buf == [0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8] + ([0] * 4)
    assert not files.out.getvalue()


def test_firmware_update_chunks_are_ignored_without_a_buffer(sm, files):
    data = struct.pack("<LL", 4, 2) + b"\x01\x02"

    process(sm, frame(UPGRADE_WRITE, data), files, PASSIVE_MODE)

    assert files.update_buf == []


def test_firmware_update_chunks_are_not_answered(sm, files):
    data = struct.pack("<LL", 0, 2) + b"\x01\x02"
    files.update_buf = list(bytes(4))

    process(sm, frame(UPGRADE_WRITE, data), files)

    assert files.update_buf == [1, 2, 0, 0]
    assert not files.line.written


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
    ("req", "_"),
    cases("master-grant-ack", first_exchanges(GRANT_ACK)),
)
def test_master_grant_ack_releases_the_bus(sm, files, req, _):
    process(sm, req, files)

    assert sm.masterEvent.is_set()
    assert files.state["masterEvent"][1] is True
    assert not files.line.written


@pytest.mark.xfail(strict=True, reason="Issue #13")
def test_master_grant_ack_with_data_releases_the_bus(sm, files):
    process(sm, frame(GRANT_ACK, b"\x01\x02"), files)

    assert sm.masterEvent.is_set()


@pytest.mark.parametrize(
    ("req", "_"),
    cases("post-data", first_exchanges(POST_DATA))
    + cases("time-request", first_exchanges(GET_GMT))
    + cases("encryption-key", first_exchanges(ENCRYPTION_KEY))
    + cases("master-grant-ack", first_exchanges(GRANT_ACK)),
)
def test_passive_mode_never_replies(sm, files, req, _):
    process(sm, req, files, PASSIVE_MODE)

    assert not files.line.written
    assert not files.rec.getvalue()
    assert not sm.masterEvent.is_set()


@pytest.mark.parametrize(
    ("req", "_"),
    cases("encrypted-data", first_exchanges(ENCRYPTED_DATA))
    + cases("master-grant", first_exchanges(GRANT))
    + cases("acknowledgment", first_exchanges(ACK)),
)
def test_other_functions_are_not_answered(sm, files, req, _):
    process(sm, req, files)

    assert not files.line.written
    assert not sm.masterEvent.is_set()


# --- readData ----------------------------------------------------------------


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
    assert not sm.threadLock.locked()


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
    monkeypatch.setattr(sm, "processMsg", lambda msg, *_rest: seen.append(msg))
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
    assert not sm.threadLock.locked()
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
    assert not sm.threadLock.locked()


def test_firmware_update_is_written_when_all_is_read(sm, files, monkeypatch):
    written = []
    monkeypatch.setattr(
        sm, "writeUpdate", lambda buf, name: written.append((buf, name))
    )
    chunk = b"\xde\xad\xbe\xef"
    files.line = FakeLine(
        b"x" + MAGIC + frame(UPGRADE_WRITE, struct.pack("<LL", 0x10, 4) + chunk)
    )

    read(sm, files, updatefile="firmware.bin")

    ((buf, name),) = written
    assert name == "firmware.bin"
    assert len(buf) == sm.UPDATE_SIZE
    assert bytes(buf[0x10:0x14]) == chunk
    assert not any(buf[:0x10]) and not any(buf[0x14:])


def test_no_firmware_update_is_written_without_a_file(
    sm, files, monkeypatch, sample
):
    monkeypatch.setattr(sm, "writeUpdate", pytest.fail)
    good, _ = recorded_exchange(sample, POST_DATA, carries_data)
    files.line = FakeLine(b"x" + MAGIC + good)

    read(sm, files)


@pytest.mark.xfail(strict=True, reason="Issue #20")
def test_update_collected_by_reading_is_written_to_the_file(sm, files):
    chunk = b"\xde\xad\xbe\xef"
    files.line = FakeLine(
        b"x" + MAGIC + frame(UPGRADE_WRITE, struct.pack("<LL", 0x10, 4) + chunk)
    )

    read(sm, files, updatefile="firmware.bin")

    image = Path("firmware.bin").read_bytes()
    assert len(image) == sm.UPDATE_SIZE
    assert image[0x10:0x14] == chunk


# --- writeUpdate -------------------------------------------------------------


def test_update_is_written_from_chunks_of_bytes(sm, caplog):
    with caplog.at_level(logging.INFO):
        sm.writeUpdate([b"\x01", b"\x02", b"\x03"], "firmware.bin")

    assert Path("firmware.bin").read_bytes() == b"\x01\x02\x03"
    assert "writing firmware.bin" in caplog.text


@pytest.mark.xfail(strict=True, reason="Issue #20")
def test_update_option_writes_the_firmware_image(
    run_semonitor, golden, sm, sample
):
    rec = golden("rec", sample)

    result = run_semonitor("-u", "firmware.bin", rec)

    assert result.returncode == 0
    assert Path("firmware.bin").stat().st_size == sm.UPDATE_SIZE


# --- masterGrant -------------------------------------------------------------


@pytest.mark.parametrize(
    ("grant", "_"),
    cases("master-grant", first_exchanges(GRANT)),
)
def test_master_grant_sends_the_grant_of_the_real_master(
    sm, files, monkeypatch, grant, _
):
    fake_bus(sm, monkeypatch)  # or the real 10 second timeout is waited for
    seq, _, dest, _ = fields(grant)
    slave_arg = f"{dest:08x}"
    Path(sm.SEQ_FILE_NAME).write_text(f"{seq - 1}\n")

    sm.masterGrant(files.state, files.line, files.rec, slave_arg)

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
        lock_held["write"].append(sm.threadLock.locked())
        return write(data)

    def slave_releases_the_bus():
        lock_held["wait"].append(sm.threadLock.locked())
        bus.event.set()

    monkeypatch.setattr(files.line, "write", probe_write)
    bus.event.on_wait = slave_releases_the_bus

    sm.masterGrant(files.state, files.line, files.rec, SLAVE_ARG)

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
        sm.masterGrant(files.state, files.line, files.rec, SLAVE_ARG)

    assert "RS485 master ack timeout" in caplog.text
    assert bus.event.is_set()
    assert bus.timers[0].canceled
    assert files.state["masterTimer"][1] is False


# --- masterCommands ----------------------------------------------------------


def test_master_commands_grant_all_slaves_over_and_over(sm, files, monkeypatch):
    granted = []
    sleeps = []

    def grant(state, line, rec, slave):
        granted.append((state, line, rec, slave))

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoop

    monkeypatch.setattr(sm, "masterGrant", grant)
    monkeypatch.setattr(sm, "time", fake_time(sleep=sleep))

    slaves = ["a1", "b2"]

    with pytest.raises(StopLoop):
        sm.masterCommands(files.state, files.line, files.rec, slaves)

    assert granted == [
        (files.state, files.line, files.rec, slave) for slave in slaves * 2
    ]
    assert sleeps == [sm.MASTER_MSG_INTERVAL] * 2
    assert files.state["masterThread"][1] is True


# --- doCommands --------------------------------------------------------------


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

    sm.doCommands(
        args, COMMAND_MODE, files.state, files.line, files.rec, files.out
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


def test_unsigned_parameters_of_a_command_are_sent_unsigned(
    sm, files, command_run
):
    args = make_args(commands=[["1f", "HFFFF", "LFFFFFFFF"]], slaves=["7f"])

    sm.doCommands(
        args, COMMAND_MODE, files.state, files.line, files.rec, files.out
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

    def grant(state, line, rec, slave):
        sent_when_granted.append((len(line.written), slave))

    monkeypatch.setattr(sm, "masterGrant", grant)
    args = make_args(commands=COMMANDS, slaves=[SLAVE_ARG, "ignored"])

    sm.doCommands(
        args, MASTER_MODE, files.state, files.line, files.rec, files.out
    )

    first_length = len(sent_commands()[0])
    assert sent_when_granted == [
        (first_length, SLAVE_ARG),
        (len(b"".join(sent_commands())), SLAVE_ARG),
    ]
    assert command_run.sleeps == [sm.COMMAND_DELAY] * 2


# --- startMaster -------------------------------------------------------------


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
        sm.startMaster(args)

    (thread,) = created
    assert thread.kwargs == {
        "name": "master thread",
        "target": sm.masterCommands,
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


# --- nextSeq -----------------------------------------------------------------


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

    assert sm.nextSeq() == expected
    assert Path(sm.SEQ_FILE_NAME).read_text() == f"{expected}\n"


def test_sequence_numbers_keep_counting(sm):
    assert [sm.nextSeq() for _ in range(3)] == [1, 2, 3]


def test_next_sequence_number_fails_when_it_can_not_be_saved(sm):
    Path(sm.SEQ_FILE_NAME).mkdir()

    with pytest.raises(OSError, match=r"seseq\.txt"):
        sm.nextSeq()


@pytest.mark.xfail(strict=True, reason="Issue #14")
@pytest.mark.parametrize("stored", ["garbage\n", ""])
def test_next_sequence_number_restarts_after_a_damaged_file(sm, stored):
    Path(sm.SEQ_FILE_NAME).write_text(stored)

    assert sm.nextSeq() == 1
    assert Path(sm.SEQ_FILE_NAME).read_text() == "1\n"


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
    monkeypatch.setattr(time, "sleep", lambda _: None)
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
    assert master.spec["target"].__name__ == "masterCommands"
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
