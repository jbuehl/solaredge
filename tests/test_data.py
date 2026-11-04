import io
import json
import math
import struct
import time
import types

import pytest

import se.commands
import se.data
import se.dataparams
import se.logutils
import se.msg

from .conftest import GOLDEN_DIR

# --- constants and tables ----------------------------------------------------

# Input for the tests: a timestamp, 1970-01-02 01:01:01 UTC, which is
# 86400 + 3600 + 60 + 1 seconds. Every part of it is non-zero, so a part that
# is dropped or scaled wrongly shows. The tests run in UTC. The STAMP_* values
# are how it is expected to be formatted.
STAMP = 90061
STAMP_DATE = "1970-01-02"
STAMP_TIME = "01:01:01"
STAMP_ASC = "Fri Jan  2 01:01:01 1970"
# Input: a device ID with the extra bit (0x00800000) set, and its parsed form.
RAW_ID = 0x7F904920
PARSED_ID = "7F104920"
# Input: the "not populated" float, which some fields turn into a nan.
FLOAT_NAN = struct.pack("<L", 0xFF7FFFFF)

# The mode to read a recording like a passive sniffer on a RS485 bus does.
PASSIVE = types.SimpleNamespace(
    passiveMode=True, serialType="4", following=False
)

# Function codes whose messages carry no arguments.
NO_ARGUMENT_FUNCTIONS = [
    se.commands.PROT_RESP_ACK,
    se.commands.PROT_RESP_NACK,
    se.commands.PROT_CMD_MISC_GET_VER,
    se.commands.PROT_CMD_MISC_GET_TYPE,
    se.commands.PROT_CMD_SERVER_GET_GMT,
    se.commands.PROT_CMD_SERVER_GET_NAME,
    se.commands.PROT_CMD_POLESTAR_GET_STATUS,
    se.commands.PROT_CMD_POLESTAR_MASTER_GRANT,
    se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK,
]

# (function, payload, what the payload is decoded to)
DECODED_FUNCTIONS = {
    "get-single-param": (
        se.commands.PROT_CMD_PARAMS_GET_SINGLE,
        struct.pack("<H", 0x1234),
        {"param": 0x1234},
    ),
    "upgrade-start": (
        se.commands.PROT_CMD_UPGRADE_START,
        struct.pack("<H", 0xBEEF),
        {"param": 0xBEEF},
    ),
    "get-type-response": (
        se.commands.PROT_RESP_MISC_GET_TYPE,
        struct.pack("<H", 0x0042),
        {"param": 0x0042},
    ),
    "reset": (
        se.commands.PROT_CMD_MISC_RESET,
        struct.pack("<LH", 0xDEADBEEF, 3),
        {"value": 0xDEADBEEF, "type": 3},
    ),
    "single-param-response": (
        se.commands.PROT_RESP_PARAMS_SINGLE,
        struct.pack("<LH", 0x01020304, 0x0A0B),
        {"value": 0x01020304, "type": 0x0A0B},
    ),
    "version-response": (
        se.commands.PROT_RESP_MISC_GET_VER,
        struct.pack("<HHxx", 3, 14),
        {"version": "0003.0014"},
    ),
    "set-single-param": (
        se.commands.PROT_CMD_PARAMS_SET_SINGLE,
        struct.pack("<HL", 0x0102, 0x0A0B0C0D),
        {"param": 0x0102, "value": 0x0A0B0C0D},
    ),
    "upgrade-write": (
        se.commands.PROT_CMD_UPGRADE_WRITE,
        struct.pack("<LL", 0x100, 4) + b"\x01\x02\x03\x04",
        {"offset": 0x100, "length": 4, "data": b"\x01\x02\x03\x04"},
    ),
    "upgrade-write-without-data": (
        se.commands.PROT_CMD_UPGRADE_WRITE,
        struct.pack("<LL", 0, 0),
        {"offset": 0, "length": 0, "data": b""},
    ),
    "upgrade-size-response": (
        se.commands.PROT_RESP_UPGRADE_SIZE,
        struct.pack("<L", 0x00ABCDEF),
        {"param": 0x00ABCDEF},
    ),
    "time-response": (
        se.commands.PROT_RESP_SERVER_GMT,
        struct.pack("<Ll", STAMP, -3600),
        {"time": STAMP, "tz": -3600},
    ),
    "status-response": (
        se.commands.PROT_RESP_POLESTAR_GET_STATUS,
        b"",
        {"status": 0},
    ),
    "energy-statistics": (
        se.commands.PROT_RESP_POLESTAR_GET_ENERGY_STATISTICS_STATUS,
        struct.pack("<ffffL", 1.5, 2.5, 3.5, 4.5, STAMP) + b"\x00\x00",
        {
            "Eday": 1.5,
            "Emon": 2.5,
            "Eyear": 3.5,
            "Etot": 4.5,
            "Time1": STAMP_ASC,
        },
    ),
}


# --- helpers -----------------------------------------------------------------


def read_frames(sample):
    frames = []
    state = {}
    with (GOLDEN_DIR / "rec" / f"{sample}.rec").open("rb") as rec:
        while True:
            msg, eof = se.msg.readMsg(rec, None, PASSIVE, state)
            if msg:
                function, data = se.msg.parseMsg(msg)[3:]
                if function:
                    frames.append((function, data))
            if eof:
                return frames


def frames_of(sample, function):
    return [data for func, data in read_frames(sample) if func == function]


def pack_fields(fmt, values):
    return struct.pack(
        fmt,
        *(
            values.get(i, 0.0 if code == "f" else 0)
            for i, code in enumerate(fmt[1:])
        ),
    )


def device(se_type, se_id, payload):
    return struct.pack("<HLH", se_type, se_id, len(payload)) + payload


def packed_optimizer_bits(vpan, vopt, imod):
    return bytes(
        [
            vpan & 0xFF,
            (vpan >> 8) | ((vopt & 0x3F) << 2),
            (vopt >> 6) | ((imod & 0xF) << 4),
            imod >> 4,
        ]
    )


# The payload of a 0x0080 or 0x0082 optimizer.
def new_optimizer_payload(uptime, extra):
    # The panel voltage is 0x155 / 8 = 42.625 V, the optimizer voltage is
    # 0x2AA / 8 = 85.25 V and the panel current is 0x333 / 160 = 5.11875 A.
    return (
        struct.pack("<LH", STAMP, uptime)
        + packed_optimizer_bits(0x155, 0x2AA, 0x333)
        + extra
    )


def inverter_values():
    return {
        0: STAMP,
        1: 1000,
        2: 300,
        3: 41.5,
        4: 2500.0,
        5: 12.5,
        6: 230.25,
        7: 1.75,
        8: 50.0,
        11: 380.5,
        13: 123456.0,
        18: 5000.0,
        23: 400.5,
    }


EXPECTED_INVERTER = {
    "Date": STAMP_DATE,
    "Time": STAMP_TIME,
    "ID": PARSED_ID,
    "Uptime": 1000,
    "Interval": 300,
    "Temp": 41.5,
    "Eday": 2500.0,
    "Eac": 12.5,
    "Vac": 230.25,
    "Iac": 1.75,
    "Freq": 50.0,
    "Vdc": 380.5,
    "Etot": 123456.0,
    "Pmax": 5000.0,
    "Pac": 400.5,
}


# The recordings.


@pytest.mark.parametrize(
    "function",
    [
        pytest.param(se.commands.PROT_CMD_POLESTAR_MASTER_GRANT, id="grant"),
        pytest.param(
            se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK, id="grant-ack"
        ),
    ],
)
def test_recorded_master_traffic_has_nothing_to_decode(sample, function):
    payloads = frames_of(sample, function)

    assert {se.data.parseData(function, data) for data in payloads} <= {""}


def test_recorded_acknowledgements_have_nothing_to_decode(sample):
    payloads = frames_of(sample, se.commands.PROT_RESP_ACK)

    assert payloads
    assert {
        se.data.parseData(se.commands.PROT_RESP_ACK, p) for p in payloads
    } == {""}


@pytest.mark.parametrize(
    ("recording", "stamp", "tz_offset"),
    [
        ("7f104920", 1451651889, -28800),
        ("d-tamm-2", 1471466027, 7200),
        ("jbuehl-20171119000004", 1511095440, -28800),
        ("oliv3r-20180218", 1518991101, 3600),
    ],
)
def test_recorded_time_reply_is_the_time_and_the_offset(
    recording, stamp, tz_offset
):
    payload = frames_of(recording, se.commands.PROT_RESP_SERVER_GMT)[0]

    assert se.data.parseData(se.commands.PROT_RESP_SERVER_GMT, payload) == {
        "time": stamp,
        "tz": tz_offset,
    }
    assert se.data.formatTime(stamp, tz_offset) == payload


@pytest.mark.parametrize(
    ("sample", "function"),
    [
        ("7f104920", 0x003D),
        ("7f104920", 0x0503),
        ("Geoff99.190801.1135.test", 0x03C2),
    ],
)
def test_recorded_unknown_functions_are_hex_dumps(sample, function, caplog):
    caplog.set_level("INFO")
    payload = frames_of(sample, function)[0]
    assert payload

    parsed = se.data.parseData(function, payload)

    assert parsed == payload.hex()
    assert f"Unknown function 0x{function:04x}" in caplog.messages


def test_recorded_posts_are_written_as_the_golden_json(sample, golden):
    out = io.BytesIO()

    for function, data in read_frames(sample):
        if function == se.commands.PROT_CMD_SERVER_POST_DATA and data:
            se.data.writeData(se.data.parseData(function, data), out)

    assert out.getvalue() == golden("json", sample).read_bytes()


# The functions without arguments.


def test_functions_without_argument_decode_to_nothing():
    for function in NO_ARGUMENT_FUNCTIONS:
        assert se.data.parseData(function, b"") == ""


@pytest.mark.xfail(strict=True, reason="Issue #13")
@pytest.mark.parametrize("function", NO_ARGUMENT_FUNCTIONS)
def test_functions_without_argument_hex_dump_a_payload_anyway(function):
    assert se.data.parseData(function, b"\x0a\xff") == "0aff"


# The functions with a simple payload.


@pytest.mark.parametrize(
    ("function", "payload", "expected"),
    DECODED_FUNCTIONS.values(),
    ids=DECODED_FUNCTIONS.keys(),
)
def test_parse_data_decodes_the_payload(function, payload, expected):
    assert se.data.parseData(function, payload) == expected


def test_parse_data_of_a_post_is_the_parsed_devices():
    payload = device(
        0x0010, RAW_ID, pack_fields(se.dataparams.invInFmt, inverter_values())
    )

    parsed = se.data.parseData(se.commands.PROT_CMD_SERVER_POST_DATA, payload)

    assert parsed == se.data.parseDeviceData(payload)
    assert parsed["inverters"][PARSED_ID] == EXPECTED_INVERTER


def test_parse_data_of_an_unknown_function_without_payload_is_empty(caplog):
    caplog.set_level("INFO")

    assert se.data.parseData(0x7FFF, b"") == ""
    assert "Unknown function 0x7fff" in caplog.messages


def test_parse_data_logs_what_it_decodes(caplog):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA)

    se.data.parseData(
        se.commands.PROT_CMD_UPGRADE_WRITE,
        struct.pack("<LL", 0x100, 0x20),
    )
    se.data.parseData(
        se.commands.PROT_RESP_SERVER_GMT, struct.pack("<Ll", STAMP, 7200)
    )

    assert "offset:   00000100" in caplog.messages
    assert "length:   00000020" in caplog.messages
    assert "time:      Fri Jan  2 01:01:01 1970" in caplog.messages
    assert "tz:        UTC+2" in caplog.messages


def test_status_is_logged_as_a_hex_dump(caplog):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA)

    parsed = se.data.parseStatus(bytes(range(18)))

    assert parsed == {"status": 0}
    assert caplog.messages == [
        "data:       00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f",
        "data:       10 11",
    ]


# The functions that format a payload.


def test_format_param_packs_a_little_endian_short():
    assert se.data.formatParam(0x1234) == b"\x34\x12"


def test_format_long_packs_a_little_endian_long():
    assert se.data.formatLong(0x01020304) == b"\x04\x03\x02\x01"


def test_format_time_packs_the_time_and_a_signed_offset():
    assert se.data.formatTime(STAMP, -3600) == struct.pack("<Ll", STAMP, -3600)


@pytest.mark.parametrize("tz_offset", [-7200, 0, 3600])
def test_format_time_is_what_parse_time_decodes(tz_offset):
    packed = se.data.formatTime(STAMP, tz_offset)

    assert se.data.parseTime(packed) == {"time": STAMP, "tz": tz_offset}


def test_format_param_value_is_what_parse_param_value_decodes():
    packed = se.data.formatParamValue(0x0102, 0x0A0B0C0D)

    assert packed == b"\x02\x01\x0d\x0c\x0b\x0a"
    assert se.data.parseParamValue(packed) == {
        "param": 0x0102,
        "value": 0x0A0B0C0D,
    }


def test_format_param_is_what_parse_param_decodes():
    assert se.data.parseParam(se.data.formatParam(0xABCD)) == {"param": 0xABCD}


def test_format_long_is_what_parse_long_decodes():
    assert se.data.parseLong(se.data.formatLong(0xABCDEF01)) == {
        "param": 0xABCDEF01
    }


@pytest.mark.xfail(strict=True, reason="Issue #37")
def test_format_value_type_is_what_parse_value_type_decodes():
    packed = se.data.formatValueType(0x1234, 0x0002)

    assert se.data.parseValueType(packed) == {"value": 0x1234, "type": 0x0002}


# The devices of a PROT_CMD_SERVER_POST_DATA.


def test_post_data_without_devices_has_only_the_empty_groups():
    assert se.data.parseDeviceData(b"") == {
        "inverters": {},
        "optimizers": {},
        "events": {},
    }


def test_single_phase_inverter():
    data = pack_fields(se.dataparams.invInFmt, inverter_values())

    parsed = se.data.parseDeviceData(device(0x0010, RAW_ID, data))

    assert parsed == {
        "inverters": {PARSED_ID: EXPECTED_INVERTER},
        "optimizers": {},
        "events": {},
    }


def test_single_phase_inverter_ignores_trailing_bytes():
    data = pack_fields(se.dataparams.invInFmt, inverter_values()) + (
        b"\xaa" * 6
    )

    parsed = se.data.parseDeviceData(device(0x0010, RAW_ID, data))

    assert parsed["inverters"] == {PARSED_ID: EXPECTED_INVERTER}


def test_single_phase_inverter_with_unpopulated_pmax_has_a_nan_pmax():
    values = inverter_values()
    # An unpopulated float is the lowest float, which is not what it means.
    values[18] = struct.unpack("<f", FLOAT_NAN)[0]
    assert values[18] < -3e38

    parsed = se.data.parseDeviceData(
        device(0x0010, RAW_ID, pack_fields(se.dataparams.invInFmt, values))
    )

    inverter = parsed["inverters"][PARSED_ID]
    pmax = inverter.pop("Pmax")
    assert math.isnan(pmax)
    assert inverter == {
        key: value for key, value in EXPECTED_INVERTER.items() if key != "Pmax"
    }


def test_three_phase_inverter():
    values = {
        0: STAMP,
        1: 2000,
        2: 900,
        3: 35.5,
        4: 8000.0,
        5: 250.0,
        6: 231.0,
        7: 232.0,
        8: 233.0,
        9: 3.5,
        10: 3.25,
        11: 3.0,
        12: 50.0,
        13: 50.25,
        14: 49.75,
        17: 700.5,
        19: 654321.0,
        20: 0.5,
        24: 0.5,
        25: 0.75,
        26: 1.0,
        27: 4,
        28: 2.0e6,
        29: 100.0,
        30: 6.5,
    }
    data = pack_fields(se.dataparams.inv3PhInFmt, values)

    parsed = se.data.parseDeviceData(device(0x0011, RAW_ID, data))

    expected = dict.fromkeys(se.dataparams.inv3PhItems[3:], 0)
    expected |= {
        "Date": STAMP_DATE,
        "Time": STAMP_TIME,
        "ID": PARSED_ID,
        "Uptime": 2000,
        "Interval": 900,
        "Temp": 35.5,
        "Eday": 8000.0,
        "Eac": 250.0,
        "Vac1": 231.0,
        "Vac2": 232.0,
        "Vac3": 233.0,
        "Iac1": 3.5,
        "Iac2": 3.25,
        "Iac3": 3.0,
        "Freq1": 50.0,
        "Freq2": 50.25,
        "Freq3": 49.75,
        "Vdc": 700.5,
        "Etot": 654321.0,
        "Idc": 0,
        "Irdc": 0.5,
        "CosPhi1": 0.5,
        "CosPhi2": 0.75,
        "CosPhi3": 1.0,
        "mode": 4,
        "GndFrR": 2.0e6,
        "data29": 100.0,
        "IoutDC": 6.5,
    }
    assert parsed["inverters"] == {PARSED_ID: expected}


def test_three_phase_inverter_keeps_the_raw_unpopulated_integers():
    values = dict.fromkeys((15, 16, 18, 31), 0xFF7FFFFF)
    data = pack_fields(se.dataparams.inv3PhInFmt, values)

    parsed = se.data.parseDeviceData(device(0x0011, RAW_ID, data))

    inverter = parsed["inverters"][PARSED_ID]
    assert inverter["EdayDC"] == 0xFF7FFFFF
    assert inverter["Edc"] == 0xFF7FFFFF
    assert inverter["Idc"] == 0xFF7FFFFF
    assert inverter["data31"] == 0xFF7FFFFF


def test_optimizer():
    values = {
        0: STAMP,
        1: RAW_ID,
        3: 4321,
        4: 38.5,
        5: 40.25,
        6: 5.5,
        7: 125.0,
        8: 33.0,
    }
    data = pack_fields(se.dataparams.optInFmt, values)

    parsed = se.data.parseDeviceData(device(0x0000, 0x00800ABC, data))

    assert parsed["optimizers"] == {
        "ABC": {
            "Date": STAMP_DATE,
            "Time": STAMP_TIME,
            "ID": "ABC",
            "Inverter": PARSED_ID,
            "Uptime": 4321,
            "Vmod": 38.5,
            "Vopt": 40.25,
            "Imod": 5.5,
            "Eday": 125.0,
            "Temp": 33.0,
        }
    }


def test_new_format_optimizer():
    # Energy of the day is 0x0110 / 4 and the temperature -10 * 2.
    extra = bytes([0x10, 0x01, 0xF6])
    data = new_optimizer_payload(258, extra)

    parsed = se.data.parseDeviceData(device(0x0080, 0x0A00DEF0, data))

    optimizer = parsed["optimizers"].pop("A00DEF0")
    assert parsed["optimizers"] == {}
    imod = optimizer.pop("Imod")
    assert imod == pytest.approx(5.11875)
    assert optimizer == {
        "Date": STAMP_DATE,
        "Time": STAMP_TIME,
        "ID": "A00DEF0",
        "Inverter": 0,
        "Uptime": 258,
        "Vmod": 42.625,
        "Vopt": 85.25,
        "Eday": 68.0,
        "Temp": -20.0,
    }


def test_s440_optimizer():
    data = new_optimizer_payload(258, b"\xaa" * 5)

    parsed = se.data.parseDeviceData(device(0x0082, 0x0A00DEF0, data))

    optimizer = parsed["optimizers"].pop("A00DEF0")
    assert parsed["optimizers"] == {}
    imod = optimizer.pop("Imod")
    assert imod == pytest.approx(5.11875)
    assert optimizer == {
        "Date": STAMP_DATE,
        "Time": STAMP_TIME,
        "ID": "A00DEF0",
        "Inverter": 0,
        "Uptime": 258,
        "Vmod": 42.625,
        "Vopt": 85.25,
        "Eday": 0,
        "Temp": 0,
    }


def test_wake_event_has_an_end_time():
    # A type 0 event has the time it started and the time it ended.
    values = {0: STAMP, 1: 0, 2: STAMP + 60, 3: STAMP + 120, 4: 0}

    parsed = se.data.parseDeviceData(
        device(0x0300, RAW_ID, pack_fields(se.dataparams.eventInFmt, values))
    )

    assert parsed["events"] == {
        PARSED_ID: {
            "Date": STAMP_DATE,
            "Time": STAMP_TIME,
            "ID": PARSED_ID,
            "Type": 0,
            "Event1": "Fri Jan  2 01:02:01 1970",
            "Event2": "Fri Jan  2 01:03:01 1970",
            "Event3": 0,
        }
    }


def test_sleep_event_has_a_time_zone_offset_and_an_end_time():
    # A type 1 event has a (signed) offset where a type 0 has its end time.
    values = {0: STAMP, 1: 1, 2: STAMP + 60, 3: -3600, 4: STAMP + 120}

    parsed = se.data.parseDeviceData(
        device(0x0300, RAW_ID, pack_fields(se.dataparams.eventInFmt, values))
    )

    assert parsed["events"] == {
        PARSED_ID: {
            "Date": STAMP_DATE,
            "Time": STAMP_TIME,
            "ID": PARSED_ID,
            "Type": 1,
            "Event1": "Fri Jan  2 01:02:01 1970",
            "Event2": -3600,
            "Event3": "Fri Jan  2 01:03:01 1970",
        }
    }


@pytest.mark.xfail(strict=True, reason="Issue #35")
def test_event_ignores_trailing_bytes():
    values = {0: STAMP, 1: 0, 2: STAMP, 3: STAMP, 4: 0}
    data = pack_fields(se.dataparams.eventInFmt, values) + (b"\x00" * 4)

    parsed = se.data.parseDeviceData(device(0x0300, RAW_ID, data))

    assert list(parsed["events"]) == [PARSED_ID]


def test_unknown_device_is_parsed_by_the_device_parser():
    data = struct.pack("<L", STAMP) + b"\xde\xad\xbe\xef"

    parsed = se.data.parseDeviceData(device(0x7777, RAW_ID, data))

    assert parsed["inverters"] == parsed["optimizers"] == parsed["events"] == {}
    record = parsed["Unknown_device_0x7777"][PARSED_ID]
    assert record["seType"] == "0x7777"
    assert record["seId"] == PARSED_ID
    assert record["Date"] == STAMP_DATE
    assert record["Time"] == STAMP_TIME
    assert record["Undeciphered_data"] == "de ad be ef"


def test_post_data_with_several_devices_is_all_parsed():
    inverter = pack_fields(se.dataparams.invInFmt, inverter_values())
    optimizers = [
        pack_fields(se.dataparams.optInFmt, {0: STAMP, 3: uptime})
        for uptime in (1, 2)
    ]
    data = (
        device(0x0000, 0x00800001, optimizers[0])
        + device(0x7777, 0x00000009, struct.pack("<L", STAMP))
        + device(0x0010, RAW_ID, inverter)
        + device(0x0000, 0x00800002, optimizers[1])
    )

    parsed = se.data.parseDeviceData(data)

    assert list(parsed["optimizers"]) == ["1", "2"]
    assert [o["Uptime"] for o in parsed["optimizers"].values()] == [1, 2]
    assert list(parsed["inverters"]) == [PARSED_ID]
    assert list(parsed["Unknown_device_0x7777"]) == ["9"]
    assert parsed["events"] == {}


def test_devices_are_logged_with_their_items(caplog):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA)
    data = pack_fields(se.dataparams.invInFmt, inverter_values())

    se.data.parseDeviceData(device(0x0010, RAW_ID, data))

    assert f"inverter:      {PARSED_ID} type: 0010 len: 0068" in caplog.messages
    assert "    Pac : 400.5" in caplog.messages


def test_log_device_logs_a_header_and_every_item(caplog):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA)

    se.data.logDevice("thing:", 0x10, "ABC", 4, {"one": 1, "two": "2"})

    assert caplog.messages == [
        "thing: ABC type: 0010 len: 0004",
        "    one : 1",
        "    two : 2",
    ]


# The helpers.


@pytest.mark.parametrize(
    ("se_id", "expected"),
    [
        (0x7F904920, "7F104920"),
        (0x7F104920, "7F104920"),
        (0x00800ABC, "ABC"),
        (0xFFFFFFFF, "FF7FFFFF"),
        (0, "0"),
        (0x1A2B3C, "1A2B3C"),
    ],
)
def test_parse_id_clears_the_extra_bit_and_uses_capitals(se_id, expected):
    assert se.data.parseId(se_id) == expected


def test_date_and_time_stamps_are_in_local_time():
    assert se.data.formatDateStamp(STAMP) == STAMP_DATE
    assert se.data.formatTimeStamp(STAMP) == STAMP_TIME


def test_date_and_time_stamps_follow_the_time_zone(monkeypatch):
    monkeypatch.setenv("TZ", "CET-1")
    time.tzset()

    assert se.data.formatDateStamp(STAMP) == STAMP_DATE
    assert se.data.formatTimeStamp(STAMP) == "02:01:01"


def test_format_date_time_is_asctime_of_local_time():
    assert se.data.formatDateTime(STAMP) == STAMP_ASC
    assert se.data.formatDateTime(0) == "Thu Jan  1 00:00:00 1970"


@pytest.mark.parametrize("stamp", ["text", 2**70])
def test_format_date_time_of_an_invalid_stamp_is_invalid(stamp, caplog):
    caplog.set_level("INFO")

    assert se.data.formatDateTime(stamp) == "invalid"
    assert caplog.messages[0].startswith(f"Invalid timestamp: {stamp} ")


@pytest.mark.xfail(strict=True, reason="Issue #38")
def test_format_date_time_of_an_out_of_range_stamp_is_the_hex_bytes(
    monkeypatch,
):

    def out_of_range(_):
        raise ValueError("year out of range")

    monkeypatch.setattr(time, "localtime", out_of_range)

    assert se.data.formatDateTime(0x12345678) == "78563412"


def test_dev_data_dict_of_an_invalid_stamp_has_invalid_date_and_time(caplog):
    caplog.set_level("INFO")

    parsed = se.data.devDataDict(
        "ABC", ["Date", "Time", "ID", "One"], [2**70, 5]
    )

    assert parsed == {
        "Date": "invalid",
        "Time": "invalid",
        "ID": "ABC",
        "One": 5,
    }
    assert caplog.messages[0].startswith(f"Invalid timestamp: {2**70} ")


# Writing the data.


def test_write_data_writes_sorted_json_lines_as_bytes():
    out = io.BytesIO()

    se.data.writeData({"b": [1, 2], "a": {"y": 1.5, "x": "text"}}, out)
    se.data.writeData({"c": None}, out)

    assert out.getvalue() == (
        b'{"a": {"x": "text", "y": 1.5}, "b": [1, 2]}\n{"c": null}\n'
    )


def test_write_data_writes_non_ascii_as_escapes_that_latin_1_can_hold():
    out = io.BytesIO()

    se.data.writeData({"name": "\u00e9\u20ac"}, out)

    assert out.getvalue() == b'{"name": "\\u00e9\\u20ac"}\n'
    assert json.loads(out.getvalue()) == {"name": "\u00e9\u20ac"}


def test_write_data_flushes_the_file():
    raw = io.BytesIO()
    buffered = io.BufferedWriter(raw, buffer_size=io.DEFAULT_BUFFER_SIZE)

    se.data.writeData({"a": 1}, buffered)

    assert raw.getvalue() == b'{"a": 1}\n'


def test_write_data_counts_the_messages_it_writes():
    before = se.data.outSeq

    se.data.writeData({"a": 1}, io.BytesIO())
    se.data.writeData({"a": 2}, io.BytesIO())

    assert se.data.outSeq == before + 2


def test_write_data_logs_the_message(caplog):
    caplog.set_level(se.logutils.LOG_LEVEL_DATA)

    se.data.writeData({"a": 1}, io.BytesIO())

    assert caplog.messages == ['{"a": 1}']


def test_write_data_without_a_file_writes_nothing():
    before = se.data.outSeq

    assert se.data.writeData({"a": 1}, None) is None

    assert se.data.outSeq == before


def test_write_data_writes_what_parse_data_decoded():
    out = io.BytesIO()
    data = pack_fields(se.dataparams.invInFmt, inverter_values())
    parsed = se.data.parseData(
        se.commands.PROT_CMD_SERVER_POST_DATA, device(0x0010, RAW_ID, data)
    )

    se.data.writeData(parsed, out)

    assert json.loads(out.getvalue())["inverters"] == {
        PARSED_ID: EXPECTED_INVERTER
    }
