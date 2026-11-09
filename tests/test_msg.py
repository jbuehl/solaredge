import io
import logging
import struct
import time
import types

import pytest

import se.env
import se.logutils
import se.msg
from tests.conftest import SAMPLES

SRC = 0xFFFFFFFE
DST = 0x7F104920
FUNCTION = 0x0501
NOTHING = (0, 0, 0, 0, b"")

DATA_LEVEL = se.logutils.LOG_LEVEL_DATA
RAW_LEVEL = se.logutils.LOG_LEVEL_RAW


def make_file(data=b""):
    file = io.BytesIO(data)
    file.name = "<test>"
    return file


def frame(seq=1, data=b"", function=FUNCTION):
    return bytes(se.msg.formatMsg(seq, SRC, DST, function, data))


def corrupt(msg, index, mask):
    broken = bytearray(msg)
    broken[index] ^= mask
    return bytes(broken)


def run_mode(*, passive, serial_type="n", following=False):
    return se.env.RunMode(
        serialDevice=True,
        serialType=serial_type,
        passiveMode=passive,
        masterMode=not passive,
        following=following,
    )


def reference_crc(data):
    crc = 0x5A5A
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def messages(caplog, level):
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def log_all(caplog, level=RAW_LEVEL):
    caplog.set_level(level, logger="se.msg")


def read_all(infile, recfile, mode):
    results = []
    eof = False
    while not eof:
        result = se.msg.readMsg(infile, recfile, mode, {})
        results.append(result)
        eof = result[1]
    return results


MAGIC = se.msg.magic
GOOD = frame(1, b"\x01\x02\x03")
EMPTY = frame(2)

SCANNING_MODES = [
    pytest.param(run_mode(passive=True), id="passive"),
    pytest.param(run_mode(passive=False, serial_type="4"), id="rs485-active"),
    pytest.param(run_mode(passive=True, serial_type="4"), id="rs485-passive"),
]
HEADER_MODES = [
    pytest.param(run_mode(passive=False, serial_type="n"), id="active-n"),
    pytest.param(run_mode(passive=False, serial_type="2"), id="active-rs232"),
]


# --- CRC and formatting ------------------------------------------------------


def test_crc_of_nothing_is_the_initial_value():
    assert se.msg.calcCrc(b"") == 0x5A5A


@pytest.mark.parametrize(
    "data",
    [b"\x00", b"\xff", b"123456789", bytes(range(256)), bytearray(b"abc")],
)
def test_crc_matches_the_bitwise_definition(data):
    assert se.msg.calcCrc(data) == reference_crc(data)


@pytest.mark.parametrize("data", [b"", b"\x01", b"hello world", bytes(300)])
def test_format_msg_layout(data):
    msg = se.msg.formatMsg(0x1234, SRC, DST, FUNCTION, data)

    header = struct.pack(
        "<HHHLLH", len(data), ~len(data) & 0xFFFF, 0x1234, SRC, DST, FUNCTION
    )
    crc = reference_crc(struct.pack(">HLLH", 0x1234, SRC, DST, FUNCTION) + data)
    assert isinstance(msg, bytearray)
    assert msg == header + data + struct.pack("<H", crc)


def test_format_msg_takes_bytearray_data_and_ignores_encrypt():
    msg = se.msg.formatMsg(7, SRC, DST, FUNCTION, bytearray(b"ab"))

    assert msg == se.msg.formatMsg(7, SRC, DST, FUNCTION, b"ab", encrypt=False)


def test_format_msg_logs_the_header(caplog):
    log_all(caplog, DATA_LEVEL)

    se.msg.formatMsg(0x1234, SRC, DST, FUNCTION, b"ab")

    assert messages(caplog, DATA_LEVEL) == [
        "dataLen:    0002",
        f"dataLenInv: {0xFFFD:04x}",
        "sequence:   1234",
        f"source:     {SRC:08x}",
        f"dest:       {DST:08x}",
        "function:   0501",
    ]


# --- parsing and validating --------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"\x01", b"x" * 100])
@pytest.mark.parametrize("parse", [se.msg.parseMsg, se.msg.validateMsg])
def test_valid_message_is_parsed(parse, data):
    msg = frame(4660, data, function=0x0080)

    assert parse(msg) == (4660, SRC, DST, 0x0080, data)


def test_message_as_bytearray_is_parsed():
    msg = se.msg.formatMsg(5, SRC, DST, FUNCTION, b"\x09")

    assert se.msg.parseMsg(msg) == (5, SRC, DST, FUNCTION, b"\x09")


def test_parse_msg_throws_out_a_message_that_is_too_short(caplog):
    log_all(caplog, DATA_LEVEL)

    assert se.msg.parseMsg(EMPTY[:-1]) == NOTHING

    assert messages(caplog, DATA_LEVEL) == [
        "Threw out a message that was too short"
    ]
    assert not messages(caplog, logging.ERROR)


@pytest.mark.parametrize("length", [0, 1, 17])
def test_validate_msg_rejects_a_message_that_is_too_short(caplog, length):
    log_all(caplog, DATA_LEVEL)
    msg = EMPTY[:length]

    assert se.msg.validateMsg(msg) == NOTHING

    assert messages(caplog, logging.ERROR) == ["Message too short"]
    assert messages(caplog, DATA_LEVEL) == list(se.logutils.format_data(msg))


@pytest.mark.parametrize(
    ("msg", "error"),
    [
        pytest.param(
            GOOD[:-1], "Data length is too big for the message", id="too-big"
        ),
        pytest.param(
            corrupt(GOOD, 0, 0x10),
            "Data length is too big for the message",
            id="length-too-big",
        ),
        pytest.param(
            corrupt(GOOD, 2, 0x01),
            "Data length doesn't match inverse length",
            id="inverse-low-byte",
        ),
        pytest.param(
            corrupt(GOOD, 3, 0x80),
            "Data length doesn't match inverse length",
            id="inverse-high-byte",
        ),
        pytest.param(
            corrupt(GOOD, -1, 0x01), "Checksum error.", id="checksum-low-byte"
        ),
        pytest.param(
            corrupt(GOOD, -2, 0x80), "Checksum error.", id="checksum-high-byte"
        ),
        pytest.param(
            corrupt(GOOD, 17, 0x04), "Checksum error.", id="corrupt-data"
        ),
        pytest.param(
            corrupt(GOOD, 4, 0x04), "Checksum error.", id="corrupt-sequence"
        ),
        pytest.param(
            corrupt(GOOD, 8, 0x04), "Checksum error.", id="corrupt-source"
        ),
        pytest.param(
            corrupt(GOOD, 14, 0x04), "Checksum error.", id="corrupt-function"
        ),
    ],
)
@pytest.mark.parametrize("parse", [se.msg.parseMsg, se.msg.validateMsg])
def test_broken_message_is_rejected_and_dumped(caplog, parse, msg, error):
    log_all(caplog, DATA_LEVEL)

    assert parse(msg) == NOTHING

    (logged,) = messages(caplog, logging.ERROR)
    assert logged.startswith(error)
    dump = list(se.logutils.format_data(msg))
    assert messages(caplog, DATA_LEVEL)[-len(dump) :] == dump


def test_extra_bytes_after_the_message_are_discarded(caplog):
    log_all(caplog, DATA_LEVEL)

    result = se.msg.parseMsg(GOOD + b"\xaa\xbb")

    assert result == (1, SRC, DST, FUNCTION, b"\x01\x02\x03")
    logged = messages(caplog, DATA_LEVEL)
    assert "Discarding 2 extra bytes" in logged
    assert logged[-1] == "data:       aa bb"
    assert not messages(caplog, logging.ERROR)


def test_extra_bytes_are_dumped_in_lines_of_16(caplog):
    log_all(caplog, DATA_LEVEL)
    extra = bytes(range(20))

    assert se.msg.parseMsg(EMPTY + extra) == (2, SRC, DST, FUNCTION, b"")

    assert "Discarding 20 extra bytes" in messages(caplog, DATA_LEVEL)
    assert messages(caplog, DATA_LEVEL)[-2:] == [
        "data:       " + " ".join(f"{x:02x}" for x in range(16)),
        "data:       10 11 12 13",
    ]


def test_message_without_extra_bytes_does_not_log_any(caplog):
    log_all(caplog, DATA_LEVEL)

    se.msg.parseMsg(GOOD)

    assert not [m for m in messages(caplog, DATA_LEVEL) if "extra" in m]


@pytest.mark.xfail(strict=True, reason="Issue #42")
def test_checksum_error_reports_the_calculated_sum_as_expected(caplog):
    log_all(caplog, DATA_LEVEL)
    calculated = struct.unpack("<H", GOOD[-2:])[0]
    received = calculated ^ 0x0101

    se.msg.parseMsg(GOOD[:-2] + struct.pack("<H", received))

    (logged,) = messages(caplog, logging.ERROR)
    sums = f"Expected 0x{calculated:04x}, got 0x{received:04x}"
    assert logged == f"Checksum error. {sums}"


# --- reading messages --------------------------------------------------------


@pytest.mark.parametrize("mode", SCANNING_MODES)
def test_read_msg_scans_for_the_magic_number(mode):
    infile = make_file(MAGIC + GOOD + MAGIC + EMPTY)
    state = {}

    results = [se.msg.readMsg(infile, None, mode, state) for _ in range(4)]

    # The first magic number has nothing in front of it, and the last message
    # is ended by the end of the file.
    assert results == [(b"", False), (GOOD, False), (EMPTY, True), (b"", True)]


@pytest.mark.parametrize("mode", SCANNING_MODES)
def test_read_msg_keeps_garbage_in_front_of_a_message(mode):
    infile = make_file(b"junk" + MAGIC + GOOD)

    assert se.msg.readMsg(infile, None, mode, {}) == (b"junk", False)
    assert se.msg.readMsg(infile, None, mode, {}) == (GOOD, True)


@pytest.mark.parametrize("mode", SCANNING_MODES)
def test_read_msg_without_any_magic_number_returns_the_rest(mode):
    assert se.msg.readMsg(make_file(b"abc"), None, mode, {}) == (b"abc", True)


@pytest.mark.parametrize("mode", HEADER_MODES)
def test_read_msg_uses_the_length_in_the_header(mode):
    infile = make_file(MAGIC + GOOD + MAGIC + EMPTY)
    state = {}

    results = [se.msg.readMsg(infile, None, mode, state) for _ in range(3)]

    assert results == [(GOOD, False), (EMPTY, False), (b"", True)]


@pytest.mark.parametrize("mode", HEADER_MODES)
def test_read_msg_leaves_the_bytes_after_a_message_unread(mode):
    infile = make_file(MAGIC + GOOD + b"rest")

    assert se.msg.readMsg(infile, None, mode, {}) == (GOOD, False)
    assert infile.read() == b"rest"


@pytest.mark.parametrize("mode", HEADER_MODES)
def test_read_msg_returns_what_is_left_of_a_truncated_message(mode):
    infile = make_file(MAGIC + GOOD[:-3])

    assert se.msg.readMsg(infile, None, mode, {}) == (GOOD[:-3], False)
    assert se.msg.readMsg(infile, None, mode, {}) == (b"", True)


@pytest.mark.xfail(strict=True, reason="Issue #21")
@pytest.mark.parametrize("mode", HEADER_MODES)
def test_read_msg_reports_the_end_of_a_file_inside_the_header(mode):
    infile = make_file(MAGIC + GOOD[:6])

    assert se.msg.readMsg(infile, None, mode, {}) == (b"", True)


@pytest.mark.parametrize("mode", SCANNING_MODES + HEADER_MODES)
def test_read_msg_records_everything_it_reads(mode):
    stream = MAGIC + GOOD + MAGIC + EMPTY
    infile = make_file(stream)
    recfile = io.BytesIO()

    read_all(infile, recfile, mode)

    assert recfile.getvalue() == stream


@pytest.mark.parametrize("mode", SCANNING_MODES + HEADER_MODES)
def test_read_msg_counts_the_messages_it_reads(mode):
    infile = make_file(MAGIC + GOOD)
    before = se.msg.dataInSeq

    se.msg.readMsg(infile, None, mode, {})
    se.msg.readMsg(infile, None, mode, {})

    assert se.msg.dataInSeq == before + 2


@pytest.mark.parametrize(
    ("mode", "last_byte", "length"),
    [
        pytest.param(SCANNING_MODES[0].values[0], "79", 1, id="scanning"),
        pytest.param(
            HEADER_MODES[0].values[0], f"{GOOD[-1]:02x}", 5, id="header"
        ),
    ],
)
def test_read_msg_keeps_track_of_its_state(mode, last_byte, length):
    state = {}

    se.msg.readMsg(make_file(MAGIC + GOOD), None, mode, state)

    assert state["passiveMode"][1] is mode.passiveMode
    assert state["serialType"][1] == mode.serialType
    assert state["readLength"][1] == length
    assert state["lastByteRead"][1] == last_byte


@pytest.mark.parametrize("mode", SCANNING_MODES + HEADER_MODES)
def test_read_msg_logs_the_message_but_not_empty_ones(caplog, mode):
    log_all(caplog)
    infile = make_file(MAGIC + GOOD)

    se.msg.readMsg(infile, None, mode, {})  # zero length for scanning
    if mode.passiveMode or mode.serialType == "4":
        assert not caplog.records
        se.msg.readMsg(infile, None, mode, {})

    seq = se.msg.dataInSeq
    length = len(MAGIC + GOOD)
    assert messages(caplog, logging.DEBUG) == [
        f"<test> --> message: {seq} length: {length}"
    ]
    assert messages(caplog, RAW_LEVEL) == list(
        se.logutils.format_data(MAGIC + GOOD)
    )


# --- reading recordings ------------------------------------------------------


def test_read_msg_splits_a_recording_at_the_magic_numbers(golden, sample):
    data = golden("rec", sample).read_bytes()
    recfile = io.BytesIO()

    results = read_all(
        make_file(data), recfile, run_mode(passive=True, serial_type="4")
    )

    msgs, eofs = zip(*results, strict=True)
    assert list(msgs) == data.split(MAGIC)
    assert list(eofs) == ([False] * (len(results) - 1)) + [True]
    assert recfile.getvalue() == data


@pytest.mark.parametrize(
    "sample",
    [
        pytest.param(
            s, marks=pytest.mark.xfail(strict=True, reason="Issue #41")
        )
        if s == "7f104920"
        else s
        for s in SAMPLES
    ],
)
def test_recorded_messages_are_valid_except_the_cut_off_one(golden, sample):
    data = golden("rec", sample).read_bytes()
    results = read_all(make_file(data), None, run_mode(passive=True))

    # The recording starts with a magic number, and the prefix may end inside
    # the last message.
    whole = [result[0] for result in results[1:-1]]

    assert whole
    for msg in whole:
        assert se.msg.validateMsg(msg) != NOTHING


# --- reading bytes -----------------------------------------------------------


def test_read_bytes_reads_and_records(caplog):
    infile = make_file(b"abcdef")
    recfile = io.BytesIO()
    state = {}

    data = se.msg.readBytes(infile, recfile, 4, run_mode(passive=True), state)

    assert data == b"abcd"
    assert recfile.getvalue() == b"abcd"
    assert infile.read() == b"ef"
    assert state["readLength"][1] == 4
    assert state["lastByteRead"][1] == "64"
    assert not caplog.records


def test_read_bytes_works_without_a_record_file():
    infile = make_file(b"\x0a\xff")

    data = se.msg.readBytes(infile, None, 2, run_mode(passive=True), {})

    assert data == b"\x0a\xff"


def test_read_bytes_returns_bytes_for_any_buffer():
    infile = types.SimpleNamespace(read=lambda _: bytearray(b"xy"))

    data = se.msg.readBytes(infile, None, 2, run_mode(passive=True), {})

    assert data == b"xy"
    assert type(data) is bytes


@pytest.mark.parametrize("record", [True, False])
def test_read_bytes_treats_the_end_of_file_as_empty(caplog, record):
    caplog.set_level(logging.INFO, logger="se.msg")
    recfile = io.BytesIO() if record else None

    data = se.msg.readBytes(make_file(), recfile, 3, run_mode(passive=True), {})

    assert data == b""
    assert any(
        m.startswith("Exception while reading data")
        for m in messages(caplog, logging.INFO)
    )
    if record:
        assert recfile.getvalue() == b""


def test_read_bytes_treats_exceptions_as_the_end_of_file(caplog):
    caplog.set_level(logging.INFO, logger="se.msg")

    def read(_):
        msg = "disk on fire"
        raise OSError(msg)

    infile = types.SimpleNamespace(read=read)

    data = se.msg.readBytes(infile, None, 3, run_mode(passive=True), {})

    assert data == b""
    assert messages(caplog, logging.INFO) == [
        "Exception while reading data: disk on fire"
    ]


def test_read_bytes_treats_a_failing_record_file_as_the_end_of_file():
    class Failing(io.BytesIO):
        def write(self, _):
            msg = "no space left"
            raise OSError(msg)

    data = se.msg.readBytes(
        make_file(b"abc"), Failing(), 3, run_mode(passive=True), {}
    )

    assert data == b""


def test_read_bytes_waits_for_the_file_to_grow_when_following(monkeypatch):
    infile = make_file()
    recfile = io.BytesIO()
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:  # somebody appends to the file
            position = infile.tell()
            infile.write(b"\x01\x02")
            infile.seek(position)

    monkeypatch.setattr(time, "sleep", sleep)
    state = {}

    data = se.msg.readBytes(
        infile, recfile, 2, run_mode(passive=True, following=True), state
    )

    assert data == b"\x01\x02"
    assert sleeps == [se.msg.sleepInterval] * 3
    assert recfile.getvalue() == b"\x01\x02"
    assert state["lastByteRead"][1] == "02"


def test_read_bytes_does_not_wait_when_following_and_data_is_there(
    monkeypatch,
):
    def sleep(_):
        pytest.fail("should not sleep")

    monkeypatch.setattr(time, "sleep", sleep)

    data = se.msg.readBytes(
        make_file(b"\x05"), None, 1, run_mode(passive=True, following=True), {}
    )

    assert data == b"\x05"


def test_read_bytes_does_not_wait_when_not_following(monkeypatch):
    def sleep(_):
        pytest.fail("should not sleep")

    monkeypatch.setattr(time, "sleep", sleep)

    assert (
        se.msg.readBytes(make_file(), None, 1, run_mode(passive=True), {})
        == b""
    )


# --- sending and recording ---------------------------------------------------


@pytest.mark.parametrize("record", [True, False])
def test_send_msg_writes_the_magic_number_and_the_message(record):
    outfile = make_file()
    recfile = io.BytesIO() if record else None
    msg = se.msg.formatMsg(3, SRC, DST, FUNCTION, b"\x01")

    se.msg.sendMsg(outfile, msg, recfile)

    assert outfile.getvalue() == MAGIC + msg
    if record:
        assert recfile.getvalue() == MAGIC + msg


def test_send_msg_counts_and_logs_the_messages(caplog):
    log_all(caplog, logging.DEBUG)
    outfile = make_file()
    msg = se.msg.formatMsg(3, SRC, DST, FUNCTION)
    before = se.msg.dataOutSeq

    se.msg.sendMsg(outfile, msg, None)
    se.msg.sendMsg(outfile, msg, None)

    assert se.msg.dataOutSeq == before + 2
    assert messages(caplog, logging.DEBUG) == [
        f"<test> <-- message: {before + 1} length: {len(MAGIC + msg)}",
        f"<test> <-- message: {before + 2} length: {len(MAGIC + msg)}",
    ]


def test_sent_message_can_be_read_again():
    outfile = make_file()
    se.msg.sendMsg(outfile, se.msg.formatMsg(9, DST, SRC, 0x0080, b"ok"), None)
    outfile.seek(0)

    msg, eof = se.msg.readMsg(outfile, None, run_mode(passive=False), {})

    assert not eof
    assert se.msg.parseMsg(msg) == (9, DST, SRC, 0x0080, b"ok")


def test_record_msg_appends_to_the_file():
    recfile = io.BytesIO()

    se.msg.recordMsg(b"ab", recfile)
    se.msg.recordMsg(b"cd", recfile)

    assert recfile.getvalue() == b"abcd"


def test_record_msg_without_a_file_does_nothing():
    assert se.msg.recordMsg(b"ab", None) is None
