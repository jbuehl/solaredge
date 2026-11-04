import collections
import functools
import json
import logging
import math
import struct
import time

import pytest

import se.commands
from se.datadevices import (
    ParseDevice,
    ParseDevice_0x0022,
    ParseDevice_0x0030,
    ParseDevice_Explorer,
    merge_update,
)
import se.msg

from .conftest import GOLDEN_DIR, SAMPLES

LOGGER = "se.datadevices"

# The seTypes that se.data parses itself, ParseDevice gets all others.
PARSED_BY_DATA = {0x0000, 0x0080, 0x0082, 0x0010, 0x0011, 0x0300}

# The decoded values of some records: (recording stem, seType, recType or
# None, expected dict). "nan" is a not reported float, as in comparable().
DECODED = [
    (
        "Geoff99.190801.1135.test",
        0x0030,
        None,
        {
            "seType": "0x0030",
            "seId": "7F1502EE",
            "devLen": 86,
            "devType": "batteries_0x0030",
            "dateTime": 1564623587,
            "Date": "2019-08-01",
            "Time": "01:39:47",
            "batteryId": "T15L0002195",
            "Vdc": 424.3999938964844,
            "Idc": 7.3279924392700195,
            "BattCapacityNom": 6400.0,
            "BattCapacityActual": 5582.0,
            "BattCharge": 4692.0,
            "TotalEnergyIn": 6584403,
            "AlwaysZero_40_float": 0.0,
            "TotalEnergyOut": 6313745,
            "AlwaysZero_48_float": 0.0,
            "HexConst_52": "ff ff 7f ff",
            "HexConst_56": "ff ff 7f ff",
            "Temp": 22.0,
            "BattChargingStatus": 3,
            "AlwaysZero_66_float": 0.0,
            "AlwaysZero_70_float": 0.0,
            "Interval": 300,
            "EIn": 251,
            "EOut": 0,
        },
    ),
    (
        "Geoff99.190801.1135.test",
        0x0022,
        5,
        {
            "seType": "0x0022",
            "seId": "7F1502EE",
            "devLen": 58,
            "devType": "meters_0x0022",
            "dateTime": 1564623587,
            "Date": "2019-08-01",
            "Time": "01:39:47",
            "recType": 5,
            "onlyIntervalData": 0,
            "TotalE2Grid": 11724474,
            "AlwaysZero_off10_int2": 0,
            "Flag_off12_hex": "00 00",
            "TotalEfromGrid": 11154495,
            "AlwaysZero_off18_int2": 0,
            "Flag_off20_hex": "00 00",
            "Totaloff22_int4": 7947709,
            "AlwaysZero_off26_int2": 0,
            "Flag_off28_hex": "00 00",
            "Totaloff30_int4": 29043144,
            "AlwaysZero_off34_int2": 0,
            "Flag_off36_hex": "00 00",
            "Interval": 300,
            "E2X": 32,
            "EfromX": 5,
            "P2X": 1525.882080078125,
            "PfromX": 0.0,
        },
    ),
    (
        "Geoff99.190801.1135.test",
        0x0022,
        3,
        {
            "seType": "0x0022",
            "seId": "7F1502EE",
            "devLen": 58,
            "devType": "meters_0x0022",
            "dateTime": 1564623587,
            "Date": "2019-08-01",
            "Time": "01:39:47",
            "recType": 3,
            "onlyIntervalData": 1,
            "TotalE2Grid": 0,
            "AlwaysZero_off10_int2": 0,
            "Flag_off12_hex": "00 80",
            "TotalEfromGrid": 0,
            "AlwaysZero_off18_int2": 0,
            "Flag_off20_hex": "00 80",
            "Totaloff22_int4": 0,
            "AlwaysZero_off26_int2": 0,
            "Flag_off28_hex": "00 80",
            "Totaloff30_int4": 0,
            "AlwaysZero_off34_int2": 0,
            "Flag_off36_hex": "00 80",
            "Interval": 300,
            "E2X": 0,
            "EfromX": 181,
            "P2X": "nan",
            "PfromX": 875.117919921875,
        },
    ),
    (
        "oliv3r-20180218",
        0x0022,
        9,
        {
            "seType": "0x0022",
            "seId": "73124CBA",
            "devLen": 58,
            "devType": "meters_0x0022",
            "dateTime": 1518978577,
            "Date": "2018-02-18",
            "Time": "18:29:37",
            "recType": 9,
            "onlyIntervalData": 1,
            "TotalE2Grid": 0,
            "AlwaysZero_off10_int2": 0,
            "Flag_off12_hex": "00 80",
            "TotalEfromGrid": 0,
            "AlwaysZero_off18_int2": 0,
            "Flag_off20_hex": "00 80",
            "Totaloff22_int4": 0,
            "AlwaysZero_off26_int2": 0,
            "Flag_off28_hex": "00 80",
            "Totaloff30_int4": 0,
            "AlwaysZero_off34_int2": 0,
            "Flag_off36_hex": "00 80",
            "Interval": 300,
            "E2X": 0,
            "EfromX": 0,
            "P2X": 0.0,
            "PfromX": "nan",
        },
    ),
    (
        "oliv3r-20180218",
        0x0018,
        None,
        {
            "seType": "0x0018",
            "seId": "73124CBA",
            "devLen": 18,
            "devType": "Unknown_device_0x0018",
            "dateTime": 1518980581,
            "Date": "2018-02-18",
            "Time": "19:03:01",
            "Undeciphered_data": "13 00 4e 65 74 68 65 72 6c 61 6e 64 73 00",
        },
    ),
    (
        "oliv3r-20180218",
        0x0043,
        None,
        {
            "seType": "0x0043",
            "seId": "73124CBA",
            "devLen": 97,
            "devType": "Unknown_device_0x0043",
            "dateTime": 1518980581,
            "Date": "2018-02-18",
            "Time": "19:03:01",
            "Undeciphered_data": (
                "01 00 01 00 05 00 11 00 dd 0a 43 20 00 c3 0a 43 | "
                "20 00 d3 8c dd 10 00 67 01 dd 10 00 fd cd 42 20 | "
                "00 15 dc 42 20 00 2d e3 dc 10 00 07 dc 42 20 00 | "
                "e5 09 43 20 00 84 90 dd 10 00 f4 db 42 20 00 e2 | "
                "db 42 20 00 ff db 42 20 00 6b 04 dd 10 00 53 e7 | "
                "dc 10 00 05 0a 43 20 00 fe 7f 42 20 00"
            ),
        },
    ),
    (
        "oliv3r-20180218",
        0x0041,
        None,
        {
            "seType": "0x0041",
            "seId": "73124CBA",
            "devLen": 40,
            "devType": "Unknown_device_0x0041",
            "dateTime": 1518980581,
            "Date": "2018-02-18",
            "Time": "19:03:01",
            "Undeciphered_data": (
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 ff | "
                "ff 7f ff 01 00 00 00 00 ff ff 7f ff 00 00 00 00 | "
                "00 00 00 00"
            ),
        },
    ),
]

# The byte offsets of the fields in the payload (after the 8 byte header).
BATTERY_ZERO_48 = 48
METER_REC_TYPE = 4
METER_ZERO_26 = 26
METER_E2X = 42
METER_P2X = 50


@functools.cache
def recorded_messages(rec_path):
    messages = []
    for raw in rec_path.read_bytes().split(se.msg.magic)[1:]:
        function, data = se.msg.parseMsg(raw)[3:]
        if function != se.commands.PROT_CMD_SERVER_POST_DATA or not data:
            continue
        records = []
        ptr = 0
        while ptr < len(data):
            dev_len = struct.unpack_from("<H", data, ptr + 6)[0]
            records.append(data[ptr : ptr + 8 + dev_len])
            ptr += 8 + dev_len
        messages.append(tuple(records))
    return tuple(messages)


def se_type_of(record):
    return struct.unpack_from("<H", record)[0]


def rec_type_of(record):
    return record[8 + METER_REC_TYPE]


def parsed_by_parse_device(rec_path):
    return [
        [rec for rec in message if se_type_of(rec) not in PARSED_BY_DATA]
        for message in recorded_messages(rec_path)
    ]


def records_of_type(se_type):
    return [
        (sample, rec)
        for sample in SAMPLES
        for message in recorded_messages(GOLDEN_DIR / "rec" / f"{sample}.rec")
        for rec in message
        if se_type_of(rec) == se_type
    ]


def record_params(se_type, tag=None):
    counts = collections.Counter()
    params = []
    for stem, rec in records_of_type(se_type):
        counts[stem] += 1
        index = counts[stem]
        label = f"{stem}-{tag(rec)}-{index}" if tag else f"{stem}-{index}"
        params.append(pytest.param(rec, id=label))
    return params


def meter_params(*rec_types):
    return [
        param for param in METERS if rec_type_of(param.values[0]) in rec_types
    ]


def _retag(params, prefix, explorer):
    return [
        pytest.param(param.values[0], explorer, id=f"{prefix}-{param.id}")
        for param in params
    ]


BATTERIES = record_params(0x0030)
METERS = record_params(0x0022, lambda rec: f"rec{rec_type_of(rec)}")
UNKNOWN = record_params(0x0018)


def table_row(se_type, rec_type=None):
    (row,) = [
        row for row in DECODED if row[1] == se_type and row[2] == rec_type
    ]
    return row


def table_expected(se_type, rec_type=None):
    return table_row(se_type, rec_type)[3]


def table_record(se_type, rec_type=None):
    stem = table_row(se_type, rec_type)[0]
    return next(
        rec
        for sample, rec in records_of_type(se_type)
        if sample == stem and (rec_type is None or rec_type_of(rec) == rec_type)
    )


def resized(record, payload):
    return record[:6] + struct.pack("<H", len(payload)) + payload


def patched(record, offset, new_bytes):
    start = 8 + offset
    return record[:start] + new_bytes + record[start + len(new_bytes) :]


def payload_of(record):
    return record[8:]


def comparable(device):
    return {
        key: "nan" if isinstance(value, float) and math.isnan(value) else value
        for key, value in device.items()
    }


# Parsing changes the class level tables (a longer record adds to fieldDefs, the
# explorer adds item names), so every test gets pristine copies.
@pytest.fixture(autouse=True)
def isolate_class_state(monkeypatch):
    for cls in (ParseDevice_0x0022, ParseDevice_0x0030, ParseDevice_Explorer):
        monkeypatch.setattr(cls, "fieldDefs", list(vars(cls)["fieldDefs"]))
    monkeypatch.setattr(
        ParseDevice_Explorer,
        "_itemNames",
        list(vars(ParseDevice_Explorer)["_itemNames"]),
    )


@pytest.fixture
def parse_calls(monkeypatch):
    calls = []

    def count(cls):
        original = vars(cls)["parseDevTable"]

        def counted(self, data):
            calls.append(type(self).__name__)
            return original(self, data)

        monkeypatch.setattr(cls, "parseDevTable", counted)

    count(ParseDevice)
    count(ParseDevice_Explorer)
    return calls


def raise_value_error(_):
    raise ValueError


# --- static helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    ("se_id", "expected"),
    [
        (0x7F104920, "7F104920"),
        (0x7F904920, "7F104920"),
        (0xFF7FFFFF, "FF7FFFFF"),
        (0x00000ABC, "ABC"),
        (0, "0"),
    ],
)
def test_parse_id_masks_flag_bit_and_gives_upper_case(se_id, expected):
    assert ParseDevice.parseId(se_id) == expected


def test_date_and_time_stamps_use_local_time(monkeypatch):
    stamp = 1_700_000_000  # 2023-11-14 22:13:20 UTC

    assert ParseDevice.formatDateStamp(stamp) == "2023-11-14"
    assert ParseDevice.formatTimeStamp(stamp) == "22:13:20"
    assert ParseDevice.formatDateStamp(0) == "1970-01-01"
    assert ParseDevice.formatTimeStamp(3661) == "01:01:01"

    monkeypatch.setenv("TZ", "EET-2")
    time.tzset()

    assert ParseDevice.formatDateStamp(stamp) == "2023-11-15"
    assert ParseDevice.formatTimeStamp(stamp) == "00:13:20"


@pytest.mark.parametrize(
    "method", [ParseDevice.formatDateStamp, ParseDevice.formatTimeStamp]
)
def test_unrepresentable_time_stamp_is_reported_as_invalid(caplog, method):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert method(10**20) == "invalid"

    assert len(caplog.messages) == 1
    assert caplog.messages[0].startswith(f"Invalid timestamp: {10**20} ")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", ""),
        (b"\x01", "01"),
        (b"\xde\xad\xbe\xef", "de ad be ef"),
        (bytes(range(16)), " ".join(f"{i:02x}" for i in range(16))),
        (
            bytes(range(17)),
            " ".join(f"{i:02x}" for i in range(16)) + " | 10",
        ),
        (
            bytes(range(32)),
            " | ".join(
                [
                    " ".join(f"{i:02x}" for i in range(16)),
                    " ".join(f"{i:02x}" for i in range(16, 32)),
                ]
            ),
        ),
        (
            bytes(range(33)),
            " | ".join(
                [
                    " ".join(f"{i:02x}" for i in range(16)),
                    " ".join(f"{i:02x}" for i in range(16, 32)),
                    "20",
                ]
            ),
        ),
    ],
)
def test_hex_data_wraps_after_16_bytes(data, expected):
    assert ParseDevice.hexData(data) == expected


@pytest.mark.parametrize("data", [b"", b"\x00", bytes(range(40))])
def test_unhex_data_inverts_hex_data(data):
    assert ParseDevice.unhexData(ParseDevice.hexData(data)) == data


def test_unhex_data_ignores_spaces_and_separators():
    assert ParseDevice.unhexData("00 01 | ff") == b"\x00\x01\xff"


# --- unknown devices (real records) ------------------------------------------


def test_unknown_device_is_parsed_as_timestamp_plus_hex():
    dev = ParseDevice(table_record(0x0018))

    assert type(dev) is ParseDevice
    assert comparable(dev) == table_expected(0x0018)
    assert dev.fieldDefsLen == dev["devLen"]


def test_unknown_device_hex_wraps_every_16_bytes():
    dev = ParseDevice(table_record(0x0043))

    lines = dev["Undeciphered_data"].split(" | ")

    assert [len(line.split()) for line in lines] == ([16] * 5) + [13]
    assert lines[0] == "01 00 01 00 05 00 11 00 dd 0a 43 20 00 c3 0a 43"


def test_unknown_device_hex_survives_the_not_reported_float_pattern():
    dev = ParseDevice(table_record(0x0041))

    assert comparable(dev) == table_expected(0x0041)
    assert dev["Undeciphered_data"].startswith(
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 ff | ff 7f ff 01"
    )


@pytest.mark.parametrize("record", UNKNOWN)
def test_unknown_device_of_exactly_four_bytes_has_no_hex_tail(record):
    dev = ParseDevice(resized(record, payload_of(record)[:4]))

    assert "Undeciphered_data" not in dev
    assert dev["Date"] == ParseDevice(record)["Date"]
    assert dev["devLen"] == 4


@pytest.mark.parametrize("record", UNKNOWN)
def test_unknown_device_too_short_for_a_timestamp_is_rejected(record):
    with pytest.raises(ValueError, match="more bytes, 4, than the message"):
        ParseDevice(resized(record, payload_of(record)[:2]))


@pytest.mark.parametrize("short_record", record_params(0x0040))
def test_unknown_devices_of_different_length_do_not_share_definitions(
    short_record,
):
    long_dev = ParseDevice(table_record(0x0043))
    short_dev = ParseDevice(short_record)
    again = ParseDevice(table_record(0x0043))

    assert short_dev["Undeciphered_data"] == ParseDevice.hexData(
        payload_of(short_record)[4:]
    )
    assert long_dev == again
    assert ParseDevice.fieldDefs == []  # the shared definition is under test


@pytest.mark.parametrize("record", UNKNOWN)
def test_unknown_device_is_wrapped_by_type_and_id(record):
    dev = ParseDevice(record)

    wrapped = dev.wrap_in_ids()

    assert wrapped == {dev["devType"]: {dev["seId"]: dev}}
    assert wrapped[dev["devType"]][dev["seId"]] is dev


def test_base_class_has_no_exported_items():
    assert ParseDevice.itemNames() == []


# --- batteries (0x0030) ------------------------------------------------------


def test_battery_record_is_decoded():
    dev = ParseDevice(table_record(0x0030))

    assert type(dev) is ParseDevice_0x0030
    assert comparable(dev) == table_expected(0x0030)
    assert dev.fieldDefsLen == dev["devLen"]


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_id_is_a_string_without_trailing_nulls(record):
    dev = ParseDevice(record)

    assert isinstance(dev["batteryId"], str)
    assert "\x00" not in dev["batteryId"]


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_not_reported_float_is_nan(record):
    dev = ParseDevice(patched(record, 60, b"\xff\xff\x7f\xff"))

    assert math.isnan(dev["Temp"])
    assert dev["BattCharge"] == ParseDevice(record)["BattCharge"]


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_is_wrapped_by_type_id_and_battery_id(record):
    dev = ParseDevice(record)

    assert dev.wrap_in_ids() == {
        "batteries_0x0030": {dev["seId"]: {dev["batteryId"]: dev}}
    }


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_with_trailing_bytes_keeps_them_as_hex(record):
    expected = ParseDevice(record)
    dev = ParseDevice(resized(record, payload_of(record) + b"\x01\x02\x03"))

    assert dev["devLen"] == len(payload_of(record)) + 3
    assert dev["Undeciphered_data"] == "01 02 03"
    assert dev["EOut"] == expected["EOut"]


@pytest.mark.parametrize("record", BATTERIES)
def test_trailing_bytes_become_a_part_of_the_battery_definition(record):
    ParseDevice(resized(record, payload_of(record) + b"\x01"))

    assert ParseDevice_0x0030.itemNames()[-1] == "Undeciphered_data"
    assert sum(item[0] for item in ParseDevice_0x0030.fieldDefs) == (  # idem
        len(payload_of(record)) + 1
    )


@pytest.mark.xfail(strict=True, reason="Issue #34")
@pytest.mark.parametrize("record", BATTERIES)
def test_battery_longer_than_defined_does_not_break_the_next_normal_one(
    record,
):
    expected = ParseDevice(record)
    ParseDevice(resized(record, payload_of(record) + b"\x01"))

    dev = ParseDevice(record)

    assert dev["devLen"] == len(payload_of(record))
    assert dev["EOut"] == expected["EOut"]


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_shorter_than_its_definition_is_rejected(record):
    size = len(payload_of(record))

    with pytest.raises(ValueError, match=rf"more bytes, {size}, than .* 4"):
        ParseDevice(resized(record, payload_of(record)[:4]))


def test_battery_item_names_are_the_exported_fields():
    assert ParseDevice_0x0030.itemNames() == [
        "Date",
        "Time",
        "batteryId",
        "Vdc",
        "Idc",
        "BattCapacityNom",
        "BattCapacityActual",
        "BattCharge",
        "TotalEnergyIn",
        "TotalEnergyOut",
        "Temp",
        "BattChargingStatus",
        "EIn",
        "EOut",
    ]


def failing_battery_hypothesis(record):
    return patched(record, BATTERY_ZERO_48, struct.pack("<f", 1e30))


@pytest.mark.parametrize("record", BATTERIES)
def test_battery_with_nonzero_unused_field_logs_failed_hypothesis(
    record, caplog
):
    plain = ParseDevice(record)

    with caplog.at_level(logging.WARNING):
        ParseDevice(failing_battery_hypothesis(record))

    # A set, the count is for test_failed_hypothesis_is_logged_once.
    assert set(caplog.messages) == {
        (
            f"Failed hypothesis ParseDevice_0x0030 {plain['Date']} "
            f"{plain['Time']}"
            " : abs(self['AlwaysZero_48_float']) < 10**25 is not True"
        )
    }


@pytest.mark.xfail(strict=True, reason="Issue #36")
@pytest.mark.parametrize("record", BATTERIES)
def test_failed_hypothesis_is_logged_once(record, caplog):
    with caplog.at_level(logging.WARNING):
        ParseDevice(failing_battery_hypothesis(record))

    assert len(caplog.messages) == 1


@pytest.mark.xfail(strict=True, reason="Issue #49")
@pytest.mark.parametrize("record", BATTERIES)
def test_failed_hypothesis_is_logged_by_the_module_logger(record, caplog):
    with caplog.at_level(logging.WARNING):
        ParseDevice(failing_battery_hypothesis(record))

    assert {record.name for record in caplog.records} == {LOGGER}


@pytest.mark.parametrize("record", [*BATTERIES, *METERS])
def test_recorded_batteries_and_meters_satisfy_the_hypotheses(record, caplog):
    with caplog.at_level(logging.DEBUG):
        ParseDevice(record)

    assert caplog.messages == []


# --- meters (0x0022) ---------------------------------------------------------


def test_meter_grid_record_is_decoded():
    dev = ParseDevice(table_record(0x0022, 5))

    assert type(dev) is ParseDevice_0x0022
    assert comparable(dev) == table_expected(0x0022, 5)
    assert dev.fieldDefsLen == dev["devLen"]


def test_meter_consumption_record_has_interval_data_only():
    dev = ParseDevice(table_record(0x0022, 3))

    assert comparable(dev) == table_expected(0x0022, 3)


@pytest.mark.parametrize("record", meter_params(3, 9))
def test_meter_not_reported_float_is_nan_in_both_positions(record):
    dev = ParseDevice(record)

    assert math.isnan(dev["P2X"]) is (rec_type_of(record) == 3)
    assert math.isnan(dev["PfromX"]) is (rec_type_of(record) == 9)


@pytest.mark.parametrize("record", meter_params(9))
@pytest.mark.parametrize(
    ("p2x", "is_nan"),
    [
        (12.5, False),
        (-1.0e38, False),
        (-2.9e38, False),
        (-3.1e38, True),
        (-3.4e38, True),
    ],
)
def test_meter_power_below_minus_3e38_is_not_a_number(record, p2x, is_nan):
    patched_record = patched(record, METER_P2X, struct.pack("<f", p2x))

    dev = ParseDevice(patched_record)

    assert math.isnan(dev["P2X"]) is is_nan
    if not is_nan:
        assert dev["P2X"] == struct.unpack("<f", struct.pack("<f", p2x))[0]


METER_LABELS = {
    3: "3_Consumption",
    5: "5_GridImportExport",
    7: "7_Battery",
    8: "8_MostlyZeroes",
    9: "9_PVProduction",
}


@pytest.mark.parametrize(
    ("record", "label"),
    [
        pytest.param(rec, label, id=param.id)
        for param in METERS
        for rec in [param.values[0]]
        for label in [METER_LABELS.get(rec_type_of(rec))]
        if label is not None
    ],
)
def test_meter_is_wrapped_by_type_id_and_record_type(record, label):
    dev = ParseDevice(record)

    assert dev.wrap_in_ids() == {"meters_0x0022": {dev["seId"]: {label: dev}}}


UNRECOGNIZED_RECORD_TYPES = {
    4: "4_UnrecognizedRecType",
    0: "0_UnrecognizedRecType",
}


@pytest.mark.parametrize("rec_type", UNRECOGNIZED_RECORD_TYPES)
@pytest.mark.parametrize("record", meter_params(9))
def test_meter_of_unknown_record_type_is_wrapped_with_its_number(
    record, rec_type
):
    patched_record = patched(record, METER_REC_TYPE, bytes([rec_type]))

    dev = ParseDevice(patched_record)

    assert dev["recType"] == rec_type
    assert dev.wrap_in_ids() == {
        "meters_0x0022": {
            dev["seId"]: {UNRECOGNIZED_RECORD_TYPES[rec_type]: dev}
        }
    }


def test_pv_production_meter_record_is_decoded():
    dev = ParseDevice(table_record(0x0022, 9))

    assert comparable(dev) == table_expected(0x0022, 9)


@pytest.mark.parametrize("record", METERS)
def test_meter_with_nonzero_padding_logs_failed_hypothesis(record, caplog):
    plain = ParseDevice(record)
    patched_record = patched(record, METER_ZERO_26, b"\x01\x00")

    with caplog.at_level(logging.WARNING):
        ParseDevice(patched_record)

    assert set(caplog.messages) == {
        (
            f"Failed hypothesis ParseDevice_0x0022 {plain['Date']} "
            f"{plain['Time']}"
            " : self['AlwaysZero_off26_int2'] == 0 is not True"
        )
    }


def test_meter_item_names_are_the_exported_fields():
    assert ParseDevice_0x0022.itemNames() == [
        "Date",
        "Time",
        "recType",
        "onlyIntervalData",
        "TotalE2Grid",
        "Flag_off12_hex",
        "TotalEfromGrid",
        "Flag_off20_hex",
        "Totaloff22_int4",
        "Flag_off28_hex",
        "Totaloff30_int4",
        "Flag_off36_hex",
        "Interval",
        "E2X",
        "EfromX",
        "P2X",
        "PfromX",
    ]


# --- each record is parsed once ----------------------------------------------


@pytest.mark.parametrize(
    ("record", "explorer"),
    [
        *_retag(UNKNOWN, "unknown", explorer=False),
        *[
            pytest.param(
                *param.values,
                id=param.id,
                marks=pytest.mark.xfail(strict=True, reason="Issue #36"),
            )
            for param in [
                *_retag(BATTERIES, "battery", explorer=False),
                *_retag(METERS, "meter", explorer=False),
                *_retag(UNKNOWN, "explorer", explorer=True),
            ]
        ],
    ],
)
def test_each_record_is_parsed_once(parse_calls, record, explorer):
    ParseDevice(record, explorer=explorer)

    assert len(parse_calls) == 1


# --- derived items -----------------------------------------------------------


@pytest.mark.parametrize("record", METERS)
def test_derived_items_get_their_defaults(monkeypatch, record):
    monkeypatch.setattr(
        ParseDevice_0x0022,
        "_derivn",
        [
            ["Extra", "0.5", True, "net power"],
            ["Label", "'none'", False, "a label"],
        ],
    )

    dev = ParseDevice(record)

    assert dev["Extra"] == 0.5
    assert dev["Label"] == "none"


def test_derived_items_are_exported_after_the_defined_ones(monkeypatch):
    monkeypatch.setattr(
        ParseDevice_0x0022,
        "_derivn",
        [["Extra", "0", True, "shown"], ["Hidden", "0", False, "not shown"]],
    )

    names = ParseDevice_0x0022.itemNames()

    assert names[-1] == "Extra"
    assert "Hidden" not in names


# --- date and time problems --------------------------------------------------


@pytest.mark.parametrize("record", BATTERIES)
@pytest.mark.parametrize(
    ("method", "key", "placeholder"),
    [
        ("formatDateStamp", "Date", "1970-01-01"),
        ("formatTimeStamp", "Time", "00:00:01"),
    ],
)
def test_timestamp_that_cannot_be_formatted_gets_a_placeholder(
    monkeypatch, caplog, record, method, key, placeholder
):
    plain = ParseDevice(record)
    other = "Time" if key == "Date" else "Date"
    what = "date" if key == "Date" else "time"
    monkeypatch.setattr(ParseDevice, method, staticmethod(raise_value_error))

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        dev = ParseDevice(record)

    assert dev[key] == placeholder
    assert dev[other] == plain[other]
    assert set(caplog.messages) == {
        f"'{plain['dateTime']}' is not a valid {what}, "
        f"changed to '{placeholder}'"
    }


# --- explorer ----------------------------------------------------------------

ONE_BYTE = ("1_hex1",)
TWO_BYTES = (*ONE_BYTE, "1_hex2", "4_int2")
FOUR_BYTES = (*TWO_BYTES, "1_hex4", "3_float_LE", "3_float_BE", "4_int4")


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_parses_unknown_device_every_way_it_can(record):
    payload = payload_of(record)
    plain = ParseDevice(record)

    dev = ParseDevice(record, explorer=True)

    assert type(dev) is ParseDevice_Explorer
    assert dev["seType"] == "0x0018"
    assert dev["seId"] == plain["seId"]
    assert dev["devLen"] == len(payload)
    assert dev["devType"] == "explore_0x0018"
    assert dev["AllAsHex"] == ParseDevice.hexData(payload)
    assert dev["offset000_1_hex1"] == ParseDevice.hexData(payload[:1])
    assert dev["offset000_1_hex2"] == ParseDevice.hexData(payload[:2])
    assert dev["offset000_4_int2"] == struct.unpack_from("<H", payload)[0]
    assert dev["offset000_1_hex4"] == ParseDevice.hexData(payload[:4])
    assert dev["offset000_3_float_LE"] == struct.unpack("<f", payload[:4])[0]
    assert dev["offset000_3_float_BE"] == struct.unpack(">f", payload[:4])[0]
    assert dev["offset000_4_int4"] == struct.unpack_from("<I", payload)[0]
    assert dev["Date_offset000"] == plain["Date"]
    assert dev["Time_offset000"] == plain["Time"]
    assert dev["offset004_4_int2"] == struct.unpack_from("<H", payload, 4)[0]
    assert dev.fieldDefsLen == len(payload)


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_takes_date_and_time_from_the_first_offset(record):
    dev = ParseDevice(record, explorer=True)

    assert dev["Date"] == ParseDevice(record)["Date"]
    assert dev["Time"] == ParseDevice(record)["Time"]
    assert dev["Date_offset002"] == ParseDevice.formatDateStamp(
        dev["offset002_4_int4"]
    )
    assert dev["Date_offset002"] != dev["Date"]


@pytest.mark.parametrize("record", UNKNOWN)
@pytest.mark.parametrize(
    ("dev_len", "layout"),
    [
        (1, {0: ONE_BYTE}),
        (2, {0: TWO_BYTES}),
        (3, {0: TWO_BYTES, 2: ONE_BYTE}),
        (5, {0: FOUR_BYTES, 2: TWO_BYTES, 4: ONE_BYTE}),
    ],
)
def test_explorer_only_parses_the_bytes_that_exist(record, dev_len, layout):
    dev = ParseDevice(
        resized(record, payload_of(record)[:dev_len]), explorer=True
    )

    assert {key for key in dev if key.startswith("offset")} == {
        f"offset{offset:03}_{kind}"
        for offset, kinds in layout.items()
        for kind in kinds
    }
    assert dev.fieldDefsLen == dev_len


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_item_names_list_everything_it_parsed(record):
    ParseDevice(resized(record, payload_of(record)[:2]), explorer=True)

    names = ParseDevice_Explorer.itemNames()

    assert list(dict.fromkeys(names)) == [
        "seType",
        "seId",
        "devLen",
        "devType",
        "offset000_1_hex1",
        "offset000_1_hex2",
        "offset000_4_int2",
    ]


@pytest.mark.xfail(strict=True, reason="Issue #36")
@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_item_names_are_not_repeated(record):
    ParseDevice(record, explorer=True)

    names = ParseDevice_Explorer.itemNames()

    assert len(names) == len(set(names))


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_parse_at_offset_beyond_the_data_adds_nothing(record):
    dev = ParseDevice(resized(record, payload_of(record)[:2]), explorer=True)
    before = dict(dev)

    dev.parseAtOffset(payload_of(record)[:2], 2, 2)

    assert dev == before


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_item_is_wrapped_by_its_type(record):
    dev = ParseDevice(record, explorer=True)

    wrapped = dev.wrap_in_ids()

    assert list(wrapped) == ["explore_0x0018"]
    assert list(wrapped["explore_0x0018"].values()) == [dev]


@pytest.mark.xfail(strict=True, reason="Issue #43")
@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_item_is_wrapped_by_the_same_id_as_other_devices(record):
    explored = ParseDevice(record, explorer=True)
    plain = ParseDevice(record)

    assert list(explored.wrap_in_ids()["explore_0x0018"]) == list(
        plain.wrap_in_ids()["Unknown_device_0x0018"]
    )


@pytest.mark.parametrize("record", UNKNOWN)
def test_explorer_marks_offsets_that_are_not_a_date(monkeypatch, record):
    monkeypatch.setattr(
        ParseDevice, "formatDateStamp", staticmethod(raise_value_error)
    )

    dev = ParseDevice(resized(record, b"\x01\x00\x00\x00"), explorer=True)

    assert dev["Date_offset000"] == "1 is not a Date"
    assert dev["Time_offset000"] == "1 is not a Time"
    assert "Date" not in dev


@pytest.mark.parametrize("record", BATTERIES)
def test_explorer_is_not_used_for_known_devices(record):
    dev = ParseDevice(record, explorer=True)

    assert type(dev) is ParseDevice_0x0030


# --- documentation of the definitions ----------------------------------------


def test_item_defs_describes_every_field_of_a_device():
    text = ParseDevice_0x0030.itemDefs()

    assert "ParseDevice_0x0030 / batteries_0x0030 parses data blocks" in text
    assert "seType = 0x0030." in text
    assert "batteryId" in text
    assert "identifier for this battery" in text
    assert "Derived items" not in text


def test_item_defs_lists_the_byte_offset_of_each_field():
    lines = ParseDevice_0x0030.itemDefs().splitlines()

    battery_id = next(line for line in lines if "batteryId" in line)
    vdc = next(line for line in lines if "| Vdc" in line)
    assert battery_id.startswith("4    (  12  )   1.0")
    assert vdc.startswith("16   (  4   )   4.0")


def test_item_defs_describes_derived_items(monkeypatch):
    monkeypatch.setattr(
        ParseDevice_0x0022, "_derivn", [["Extra", "0.5", True, "net power"]]
    )

    text = ParseDevice_0x0022.itemDefs()

    assert "Derived items" in text
    assert "(default=0.5) net power" in text


def test_item_defs_of_base_class_describes_all_known_devices():
    text = ParseDevice.itemDefs()

    assert f"seType = {0xFFFF:#06x}." in text
    assert "ParseDevice_0x0030 / batteries_0x0030 parses" in text
    assert "ParseDevice_0x0022 / meters_0x0022 parses" in text
    assert "parses data blocks with any unrecognized seType" in text


def test_item_defs_of_explorer_explains_how_it_works():
    text = ParseDevice_Explorer.itemDefs()

    assert text.startswith(
        f"\n\nParseDevice_Explorer / explore_{0xFFFF:#06x} parses data blocks"
        " with any unrecognized seType."
    )
    assert "Item names are generated automatically" in text


# --- merge_update ------------------------------------------------------------


def test_merge_update_adds_missing_keys_at_every_level():
    master = {"a": {"x": 1}, "c": {"d": {"e": 1}}}

    merge_update(master, {"a": {"y": 2}, "b": 3, "c": {"d": {"f": 4}}})

    assert master == {
        "a": {"x": 1, "y": 2},
        "b": 3,
        "c": {"d": {"e": 1, "f": 4}},
    }


def test_merge_update_does_not_touch_the_contributor():
    update = {"a": {"y": 2}}

    merge_update({"a": {"x": 1}}, update)

    assert update == {"a": {"y": 2}}


def test_merge_update_of_identical_values_is_silent(caplog):
    master = {"a": {"x": 1}}

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        merge_update(master, {"a": {"x": 1}})

    assert master == {"a": {"x": 1}}
    assert caplog.messages == []


def test_merge_update_overwrites_changed_value_and_logs_at_debug(caplog):
    master = {"a": {"x": 1}}

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        merge_update(master, {"a": {"x": 2}})

    assert master == {"a": {"x": 2}}
    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        (LOGGER, logging.DEBUG, "WARNING: For x about to overwrite 1 with 2")
    ]


def test_merge_update_does_not_report_the_overwrite_above_debug(caplog):
    master = {"a": {"x": 1}}

    with caplog.at_level(logging.INFO, logger=LOGGER):
        merge_update(master, {"a": {"x": 2}})

    assert master == {"a": {"x": 2}}
    assert caplog.messages == []


def test_merge_update_with_empty_contributor_changes_nothing():
    master = {"a": {"x": 1}}

    merge_update(master, {})

    assert master == {"a": {"x": 1}}


@pytest.mark.parametrize("battery", BATTERIES)
def test_merge_of_devices_keeps_every_battery_and_meter_record(battery):
    battery_dev = ParseDevice(battery)
    se_id = battery_dev["seId"]
    other_battery = ParseDevice(patched(battery, 4, b"T15L0000001\x00"))
    meters = [
        ParseDevice(param.values[0])
        for param in METERS
        if ParseDevice(param.values[0])["seId"] == se_id
    ]
    master = {}

    for dev in [battery_dev, other_battery, *meters]:
        merge_update(master, dev.wrap_in_ids())

    assert master["batteries_0x0030"] == {
        se_id: {
            battery_dev["batteryId"]: battery_dev,
            "T15L0000001": other_battery,
        }
    }
    assert master["meters_0x0022"] == {
        se_id: {
            next(iter(dev.wrap_in_ids()["meters_0x0022"][se_id])): dev
            for dev in meters
        }
    }


@pytest.mark.parametrize("record", METERS)
def test_merge_of_a_repeated_device_updates_its_changed_fields(record, caplog):
    first = ParseDevice(record)
    old = first["E2X"]
    new = old + 1
    second = ParseDevice(patched(record, METER_E2X, struct.pack("<H", new)))
    master = {}
    merge_update(master, first.wrap_in_ids())

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        merge_update(master, second.wrap_in_ids())

    merged = master["meters_0x0022"][first["seId"]][
        next(iter(first.wrap_in_ids()["meters_0x0022"][first["seId"]]))
    ]
    assert merged["E2X"] == new
    assert [m for m in caplog.messages if "E2X" in m] == [
        f"WARNING: For E2X about to overwrite {old} with {new}"
    ]


@pytest.mark.parametrize(
    "record",
    [
        param
        if param.id
        in (
            "Geoff99.190801.1135.test-rec5-2",
            "Geoff99.190801.1135.test-rec5-7",
        )
        else pytest.param(
            *param.values,
            id=param.id,
            marks=pytest.mark.xfail(strict=True, reason="Issue #44"),
        )
        for param in METERS
    ],
)
def test_merge_of_the_same_record_again_is_silent_even_with_nan(record, caplog):
    master = {}
    merge_update(master, ParseDevice(record).wrap_in_ids())

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        merge_update(master, ParseDevice(record).wrap_in_ids())

    assert caplog.messages == []


# --- all the recordings against the golden output ----------------------------


def test_recorded_devices_merge_to_the_golden_devices(golden, sample):
    messages = parsed_by_parse_device(golden("rec", sample))
    lines = golden("json", sample).read_text(encoding="latin-1").splitlines()
    assert len(lines) == len(messages)

    for records, line in zip(messages, lines, strict=True):
        merged = {}
        for record in records:
            merge_update(merged, ParseDevice(record).wrap_in_ids())
        expected = {
            key: value
            for key, value in json.loads(line).items()
            if key not in ("events", "inverters", "optimizers")
        }
        assert json.dumps(merged, sort_keys=True) == json.dumps(
            expected, sort_keys=True
        )


def test_recorded_device_types_are_those_of_the_samples():
    found = {
        ParseDevice(rec).devType  # the type of the record is under test
        for sample in SAMPLES
        for message in parsed_by_parse_device(
            GOLDEN_DIR / "rec" / f"{sample}.rec"
        )
        for rec in message
    }

    assert found == {
        "batteries_0x0030",
        "meters_0x0022",
        *(f"Unknown_device_{t:#06x}" for t in (0x17, 0x18, *range(0x40, 0x45))),
        f"Unknown_device_{0x800:#06x}",
    }
