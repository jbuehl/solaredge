import logging
import threading
import time
import types

import pytest

import se.logutils

LOGGER_NAME = "test_logutils.subject"
HEX_PREFIX = "data:       "


def hex_line(data):
    return HEX_PREFIX + " ".join(f"{x:02x}" for x in data)


@pytest.fixture
def logger():
    return logging.getLogger(LOGGER_NAME)


def test_the_custom_levels_are_named_and_below_debug():
    assert logging.getLevelName(se.logutils.LOG_LEVEL_DATA) == "DATA"
    assert logging.getLevelName(se.logutils.LOG_LEVEL_RAW) == "RAW"
    assert (
        se.logutils.LOG_LEVEL_RAW < se.logutils.LOG_LEVEL_DATA < logging.DEBUG
    )


# --- data and raw methods ----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "level", "name"),
    [
        ("data", se.logutils.LOG_LEVEL_DATA, "DATA"),
        ("raw", se.logutils.LOG_LEVEL_RAW, "RAW"),
    ],
)
def test_custom_method_logs_when_its_level_is_enabled(
    caplog, logger, method, level, name
):
    caplog.set_level(level, logger=LOGGER_NAME)

    getattr(logger, method)("hello %s %d", "world", 5)

    (record,) = caplog.records
    assert record.levelno == level
    assert record.levelname == name
    assert record.name == LOGGER_NAME
    assert record.getMessage() == "hello world 5"


@pytest.mark.parametrize(
    ("method", "level"),
    [
        ("data", se.logutils.LOG_LEVEL_DATA),
        ("raw", se.logutils.LOG_LEVEL_RAW),
    ],
)
def test_custom_method_is_silent_when_its_level_is_disabled(
    caplog, logger, method, level
):
    caplog.set_level(level + 1, logger=LOGGER_NAME)

    getattr(logger, method)("hello")

    assert not caplog.records


def test_raw_is_enabled_by_data_but_not_the_other_way_around(caplog, logger):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA, logger=LOGGER_NAME)
    logger.raw("raw")
    logger.data("data")

    assert [r.getMessage() for r in caplog.records] == ["data"]

    caplog.clear()
    caplog.set_level(se.logutils.LOG_LEVEL_RAW, logger=LOGGER_NAME)
    logger.raw("raw")
    logger.data("data")

    assert [r.getMessage() for r in caplog.records] == ["raw", "data"]


def test_custom_methods_pass_keyword_arguments_to_the_logger(caplog, logger):
    caplog.set_level(se.logutils.LOG_LEVEL_RAW, logger=LOGGER_NAME)

    logger.data("with extra", extra={"sample": 42})

    (record,) = caplog.records
    assert record.sample == 42


# --- message method ----------------------------------------------------------


def test_message_logs_the_direction_sequence_and_length(caplog, logger):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    logger.message("-->", 12, b"\x01\x02\x03", "/dev/ttyUSB0")

    (record,) = caplog.records
    assert record.levelno == logging.DEBUG
    assert record.getMessage() == "/dev/ttyUSB0 --> message: 12 length: 3"


def test_message_end_point_is_optional(caplog, logger):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    logger.message("<--", 1, bytearray(b"ab"))

    assert [r.getMessage() for r in caplog.records] == [
        " <-- message: 1 length: 2"
    ]


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING])
def test_message_is_silent_when_debug_is_not_enabled(caplog, logger, level):
    caplog.set_level(level, logger=LOGGER_NAME)

    logger.message("-->", 1, b"abc", "x")

    assert not caplog.records


def test_message_does_not_dump_the_data_below_raw_level(caplog, logger):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA, logger=LOGGER_NAME)

    logger.message("-->", 1, bytes(40), "x")

    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


@pytest.mark.parametrize("size", [0, 1, 16, 17, 40])
def test_message_dumps_the_data_at_raw_level(caplog, logger, size):
    caplog.set_level(se.logutils.LOG_LEVEL_RAW, logger=LOGGER_NAME)
    data = bytes(range(size))

    logger.message("-->", 3, data, "x")

    header, *dump = caplog.records
    assert header.levelno == logging.DEBUG
    assert header.getMessage() == f"x --> message: 3 length: {size}"
    assert {r.levelno for r in dump} <= {se.logutils.LOG_LEVEL_RAW}
    assert [r.getMessage() for r in dump] == list(se.logutils.format_data(data))


# --- hex dump ----------------------------------------------------------------


def test_format_data_of_nothing_has_no_lines():
    assert list(se.logutils.format_data(b"")) == []


@pytest.mark.parametrize(
    ("data", "lines"),
    [
        (b"\x00", ["00"]),
        (b"\x12\x34\xab\xff", ["12 34 ab ff"]),
        (bytes(range(16)), ["00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f"]),
        (
            bytes(range(16, 33)),
            [
                "10 11 12 13 14 15 16 17 18 19 1a 1b 1c 1d 1e 1f",
                "20",
            ],
        ),
    ],
)
def test_format_data_dumps_16_bytes_per_line(data, lines):
    assert list(se.logutils.format_data(data)) == [
        HEX_PREFIX + x for x in lines
    ]


@pytest.mark.parametrize("kind", [bytes, bytearray, list, tuple])
def test_format_data_takes_any_sequence_of_ints(kind):
    assert list(se.logutils.format_data(kind([1, 171]))) == [hex_line([1, 171])]


# --- state -------------------------------------------------------------------


def test_set_state_stores_the_time_and_the_value(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1234.5)
    state = {}

    se.logutils.setState(state, "readLength", 20)

    assert state == {"readLength": [1234.5, 20]}


def test_set_state_replaces_the_previous_value(monkeypatch):
    times = iter([1.0, 2.0, 3.0])
    monkeypatch.setattr(time, "time", lambda: next(times))
    state = {}

    se.logutils.setState(state, "a", "first")
    se.logutils.setState(state, "b", "other")
    se.logutils.setState(state, "a", "second")

    assert state == {"a": [3.0, "second"], "b": [2.0, "other"]}


def test_set_state_uses_the_current_time():
    state = {}
    before = time.time()

    se.logutils.setState(state, "x", None)

    stamp, value = state["x"]
    assert before <= stamp <= time.time()
    assert value is None


# --- dumping the state -------------------------------------------------------


def info_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "se.logutils"]


def test_dump_state_logs_the_state_variables(caplog):
    caplog.set_level(logging.INFO, logger="se.logutils")
    # The tests run in UTC, see the utc fixture in conftest.py.
    state = {"readLength": [0, 20], "lastByteRead": [3661, "79"]}

    se.logutils.dumpState(state)

    messages = info_messages(caplog)
    assert messages[0] == "state:"
    assert messages[1:3] == [
        "      00:00:00 readLength: 20",
        "      01:01:01 lastByteRead: 79",
    ]


def test_dump_state_without_state_variables_logs_the_threads(caplog):
    caplog.set_level(logging.INFO, logger="se.logutils")

    se.logutils.dumpState({})

    messages = info_messages(caplog)
    assert messages[0] == "state:"
    assert f"ThreadID: {threading.get_ident()}" in messages


def test_dump_state_logs_the_stack_trace_of_the_calling_thread(caplog):
    caplog.set_level(logging.INFO, logger="se.logutils")

    se.logutils.dumpState({})

    messages = info_messages(caplog)
    me = messages.index(f"ThreadID: {threading.get_ident()}")
    stack = messages[me + 1 :]
    frame_line = next(
        i
        for i, m in enumerate(stack)
        if m.endswith(
            "test_dump_state_logs_the_stack_trace_of_the_calling_thread"
        )
    )
    assert f'File: "{__file__}", line ' in stack[frame_line]
    # The source line of the frame follows it, indented.
    assert stack[frame_line + 1] == "            se.logutils.dumpState({})"


def test_dump_state_logs_the_stack_trace_of_other_threads(caplog):
    caplog.set_level(logging.INFO, logger="se.logutils")
    started = threading.Event()
    release = threading.Event()

    def blocked_in_this_function():
        started.set()
        release.wait(timeout=10)

    thread = threading.Thread(target=blocked_in_this_function)
    thread.start()
    try:
        assert started.wait(timeout=10)
        se.logutils.dumpState({})
    finally:
        release.set()
        thread.join()

    messages = info_messages(caplog)
    assert f"ThreadID: {thread.ident}" in messages
    assert f"ThreadID: {threading.get_ident()}" in messages
    other = messages[messages.index(f"ThreadID: {thread.ident}") :]
    assert any(m.endswith("in blocked_in_this_function") for m in other)


def test_dump_state_skips_the_source_of_frames_that_have_none(caplog):
    caplog.set_level(logging.INFO, logger="se.logutils")
    # Code compiled from a string has a file name but no source to show.
    code = compile("dump({})", "<no-source>", "exec")
    function = types.FunctionType(code, {"dump": se.logutils.dumpState})

    function()

    messages = info_messages(caplog)
    frame_line = next(i for i, m in enumerate(messages) if "<no-source>" in m)
    assert messages[frame_line].endswith("line 1, in <module>")
    assert messages[frame_line + 1].lstrip().startswith("File:")
