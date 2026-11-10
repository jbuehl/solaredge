from datetime import UTC, datetime, timedelta
import gzip
import importlib.util
import json
import logging
from pathlib import Path
import queue
import sys
import types
from typing import ClassVar

import pytest

pytest.importorskip("dateutil", reason="se2influx needs python-dateutil")

SCRIPT = Path(__file__).resolve().parent.parent / "utilities" / "se2influx.py"
# The time of the fixed_now fixture, as it is in the names of the archives.
FIXED_NOW_STAMP = "20160101123000"


class FakeInfluxClient:
    instances: ClassVar[list] = []
    databases: ClassVar[list] = []
    list_error = None
    create_error = None
    write_error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.created = []
        self.written = []
        FakeInfluxClient.instances.append(self)

    def get_list_database(self):
        if FakeInfluxClient.list_error:
            raise FakeInfluxClient.list_error
        return [{"name": name} for name in FakeInfluxClient.databases]

    def create_database(self, name):
        if FakeInfluxClient.create_error:
            raise FakeInfluxClient.create_error
        self.created.append(name)

    def write_points(self, points):
        if FakeInfluxClient.write_error:
            raise FakeInfluxClient.write_error
        self.written.append(points)


class FakeQueue:
    def __init__(self, *items):
        self.items = list(items)

    def get(self, timeout=None):
        if not self.items:
            raise queue.Empty
        return self.items.pop(0)

    def put(self, item):
        self.items.append(item)

    def qsize(self):
        return len(self.items)


class FakeClock:
    def __init__(self, step):
        self.now = 0
        self.step = step

    def time(self):
        value = self.now
        self.now += self.step
        return value

    def sleep(self, seconds):
        pass


@pytest.fixture
def se(monkeypatch):
    FakeInfluxClient.instances = []
    FakeInfluxClient.databases = ["semonitor"]
    FakeInfluxClient.list_error = None
    FakeInfluxClient.create_error = None
    FakeInfluxClient.write_error = None
    influxdb = types.ModuleType("influxdb")
    influxdb.InfluxDBClient = FakeInfluxClient
    monkeypatch.setitem(sys.modules, "influxdb", influxdb)
    spec = importlib.util.spec_from_file_location(
        "se2influx_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def make(se):
    def create(
        queue_size=100,
        log_path=None,
        max_log_size=0,
        local_tz="UTC",
        stat_timer_secs=None,
        **params,
    ):
        values = {
            "host": "influx.lan",
            "port": 8086,
            "username": "user",
            "password": "pass",
            "database": "semonitor",
            "ssl": False,
            "verify_ssl": False,
            "timeout": None,
            "retries": 3,
            "use_udp": False,
            "udp_port": 4444,
        }
        values.update(params)
        return se.Se2Influx(
            se.InfluxParams(**values),
            queue_size,
            log_path,
            max_log_size,
            local_tz,
            stat_timer_secs,
        )

    return create


@pytest.fixture
def messages(caplog):
    caplog.set_level(logging.DEBUG)
    return lambda level=None: [
        record.getMessage()
        for record in caplog.records
        if level is None or record.levelno == level
    ]


def device(**attrs):
    return {"Date": "2016-01-01", "Time": "12:37:48", **attrs}


def line(**sections):
    data = {"events": {}, "inverters": {}, "optimizers": {}}
    data.update(sections)
    return json.dumps(data) + "\n"


def run_writer(obj, *lines):
    obj.writer_queue = FakeQueue(*lines)
    obj.shutdown.set()
    obj.writer()
    (client,) = FakeInfluxClient.instances
    return client


# --- InfluxParams and the exceptions -----------------------------------------


def test_influx_params_are_the_arguments_of_the_influx_client(se):
    params = se.InfluxParams("h", 1, "u", "p", "d", True, False, 5, 2, True, 4)

    assert params.__dict__ == {
        "host": "h",
        "port": 1,
        "username": "u",
        "password": "p",
        "database": "d",
        "ssl": True,
        "verify_ssl": False,
        "timeout": 5,
        "retries": 2,
        "use_udp": True,
        "udp_port": 4,
    }


def test_the_exceptions_are_exceptions(se):
    assert issubclass(se.DateError, Exception)
    assert issubclass(se.EndOfFile, Exception)


# --- constructor -------------------------------------------------------------


def test_the_queues_are_limited_to_the_queue_size(make):
    obj = make(queue_size=7)

    assert obj.writer_queue.maxsize == 7
    assert obj.logger_queue.maxsize == 7


def test_the_shutdown_flag_starts_cleared(make):
    assert not make().shutdown.is_set()


def test_the_given_timezone_is_used(make):
    obj = make(local_tz="Europe/Amsterdam")

    assert obj.local_tz.utcoffset(
        datetime(2016, 7, 1, tzinfo=UTC)
    ) == timedelta(hours=2)
    assert obj.local_tz.utcoffset(
        datetime(2016, 1, 1, tzinfo=UTC)
    ) == timedelta(hours=1)


def test_without_a_timezone_the_timezone_of_the_machine_is_used(make):
    obj = make(local_tz=None)

    # TZ is UTC0 in the tests
    assert obj.local_tz.utcoffset(
        datetime(2016, 7, 1, tzinfo=UTC)
    ) == timedelta(0)


def test_an_unknown_timezone_ends_the_program_with_a_message(make):
    with pytest.raises(SystemExit) as exit_:
        make(local_tz="Nowhere/Land")

    assert "Nowhere/Land" in str(exit_.value.code)


def test_the_settings_are_kept(make):
    obj = make(log_path="x.log", max_log_size=5, stat_timer_secs=9, host="h")

    assert obj.log_path == "x.log"
    assert obj.max_log_size == 5
    assert obj.stat_timer_secs == 9
    assert obj.influx_params.host == "h"


# --- pop_utc_date -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tz", "date", "time_", "expected"),
    [
        ("UTC", "2016-01-01", "12:37:48", "2016-01-01T12:37:48Z"),
        ("Europe/Amsterdam", "2016-01-01", "12:00:00", "2016-01-01T11:00:00Z"),
        ("Europe/Amsterdam", "2016-07-01", "12:00:00", "2016-07-01T10:00:00Z"),
        ("America/New_York", "2016-07-01", "23:30:00", "2016-07-02T03:30:00Z"),
        ("Asia/Kolkata", "2016-01-01", "00:00:00", "2015-12-31T18:30:00Z"),
        ("UTC", "2016-02-29", "23:59:59", "2016-02-29T23:59:59Z"),
    ],
)
def test_the_inverter_time_is_converted_from_its_timezone_to_utc(
    make, tz, date, time_, expected
):
    obj = make(local_tz=tz)

    assert obj.pop_utc_date({"Date": date, "Time": time_}) == expected


def test_the_date_and_time_are_removed_from_the_data(make):
    data = device(Pac=1)

    make().pop_utc_date(data)

    assert data == {"Pac": 1}


@pytest.mark.parametrize(
    ("date", "time_"),
    [
        ("2016-13-01", "12:00:00"),
        ("2016-01-01", "25:00:00"),
        ("01-01-2016", "12:00:00"),
        ("2016-01-01", "12:00"),
        ("", ""),
        (None, None),
    ],
)
def test_a_date_that_cannot_be_read_is_a_date_error(se, make, date, time_):
    with pytest.raises(se.DateError):
        make().pop_utc_date({"Date": date, "Time": time_})


@pytest.mark.parametrize("missing", ["Date", "Time"])
def test_a_missing_date_or_time_is_a_key_error(make, missing):
    data = device()
    del data[missing]

    with pytest.raises(KeyError):
        make().pop_utc_date(data)


def test_the_date_error_keeps_the_cause(se, make):
    with pytest.raises(se.DateError) as error:
        make().pop_utc_date({"Date": "x", "Time": "y"})

    assert isinstance(error.value.__cause__, ValueError)


# --- writer: the database ----------------------------------------------------


def test_the_client_is_made_from_the_parameters(make):
    client = run_writer(make(host="db", port=9, use_udp=True))

    assert client.kwargs == {
        "host": "db",
        "port": 9,
        "username": "user",
        "password": "pass",
        "database": "semonitor",
        "ssl": False,
        "verify_ssl": False,
        "timeout": None,
        "retries": 3,
        "use_udp": True,
        "udp_port": 4444,
    }


def test_an_existing_database_is_not_created_again(make):
    FakeInfluxClient.databases = ["other", "semonitor"]

    assert run_writer(make()).created == []


def test_a_missing_database_is_created(make, messages):
    FakeInfluxClient.databases = ["other"]

    client = run_writer(make(database="solar"))

    assert client.created == ["solar"]
    assert any("solar" in message for message in messages(logging.INFO))


@pytest.mark.parametrize("failing", ["list_error", "create_error"])
def test_a_database_that_cannot_be_reached_ends_the_writer_with_an_error(
    make, messages, failing
):
    FakeInfluxClient.databases = []
    setattr(FakeInfluxClient, failing, OSError("no route to host"))
    obj = make()
    obj.writer_queue = FakeQueue(line(inverters={"I1": device(Pac=1)}))
    obj.shutdown.set()

    obj.writer()

    (client,) = FakeInfluxClient.instances
    assert client.written == []
    assert any("no route to host" in m for m in messages(logging.ERROR))
    assert obj.writer_queue.qsize() == 1


# --- writer: the points ------------------------------------------------------


def test_an_inverter_becomes_a_point_with_its_serial_as_tag(make):
    client = run_writer(
        make(), line(inverters={"7F104920": device(Pac=1.5, Vac=240)})
    )

    assert client.written == [
        [
            {
                "measurement": "inverters",
                "tags": {"serial": "7F104920"},
                "time": "2016-01-01T12:37:48Z",
                "fields": {"Pac": 1.5, "Vac": 240},
            }
        ]
    ]


def test_inverters_and_optimizers_are_written_in_one_call(make):
    client = run_writer(
        make(),
        line(
            inverters={"I1": device(Pac=1)}, optimizers={"O1": device(Vmod=2)}
        ),
    )

    (points,) = client.written
    assert [(p["measurement"], p["tags"]["serial"]) for p in points] == [
        ("inverters", "I1"),
        ("optimizers", "O1"),
    ]


def test_every_line_is_written(make):
    client = run_writer(
        make(),
        line(inverters={"I1": device(Pac=1)}),
        line(inverters={"I1": device(Pac=2)}),
    )

    assert [call[0]["fields"]["Pac"] for call in client.written] == [1, 2]


def test_events_are_not_written(make):
    client = run_writer(make(), line(events={"I1": device(Type=1)}))

    assert client.written == []


def test_a_line_without_devices_writes_nothing(make):
    assert run_writer(make(), line()).written == []


def test_nan_fields_are_left_out(make):
    client = run_writer(
        make(), line(inverters={"I1": device(Pac=1.5, Temp=float("nan"))})
    )

    assert client.written[0][0]["fields"] == {"Pac": 1.5}


def test_only_nan_floats_are_left_out(make):
    client = run_writer(
        make(),
        line(
            inverters={
                "I1": device(Pac=0.0, Name="x", Count=0, Flag=False, N=None)
            }
        ),
    )

    assert client.written[0][0]["fields"] == {
        "Pac": 0.0,
        "Name": "x",
        "Count": 0,
        "Flag": False,
        "N": None,
    }


def test_the_time_zone_of_the_inverter_is_applied(make):
    client = run_writer(
        make(local_tz="Europe/Amsterdam"),
        line(inverters={"I1": device(Pac=1)}),
    )

    assert client.written[0][0]["time"] == "2016-01-01T11:37:48Z"


def test_bad_json_is_logged_and_the_next_line_is_still_written(make, messages):
    client = run_writer(
        make(), "this is not json\n", line(inverters={"I1": device(Pac=1)})
    )

    assert len(client.written) == 1
    assert any("this is not json" in m for m in messages(logging.ERROR))


def test_json_without_inverters_or_optimizers_is_logged(make, messages):
    client = run_writer(make(), json.dumps({"events": {}}) + "\n")

    assert client.written == []
    assert any("missing required fields" in m for m in messages(logging.ERROR))


def test_a_device_without_a_date_is_logged_and_not_written(make, messages):
    client = run_writer(make(), line(inverters={"I1": {"Pac": 1}}))

    assert client.written == []
    assert messages(logging.ERROR)


def test_a_device_with_a_bad_date_is_logged_and_not_written(make, messages):
    bad = {"Date": "yesterday", "Time": "12:00:00", "Pac": 1}

    client = run_writer(make(), line(inverters={"I1": bad}))

    assert client.written == []
    assert any("converting dates" in m for m in messages(logging.ERROR))


def test_a_failing_write_is_logged_and_the_next_line_is_tried(make, messages):
    obj = make()
    obj.writer_queue = FakeQueue(
        line(inverters={"I1": device(Pac=1)}),
        line(inverters={"I1": device(Pac=2)}),
    )
    obj.shutdown.set()
    FakeInfluxClient.write_error = OSError("database is down")

    obj.writer()

    assert len(messages(logging.ERROR)) == 2
    assert obj.writer_queue.qsize() == 0
    assert all("database is down" in m for m in messages(logging.ERROR))


def test_the_writer_keeps_running_while_there_is_no_shutdown(make):
    obj = make()
    obj.writer_queue = FakeQueue()
    calls: ClassVar[list] = []

    def get(timeout=None):
        calls.append(timeout)
        if len(calls) == 3:
            obj.shutdown.set()
        raise queue.Empty

    obj.writer_queue.get = get

    obj.writer()

    assert len(calls) == 3


# --- writer: statistics ------------------------------------------------------


def test_the_number_of_points_is_logged_every_stat_timer_secs(
    se, make, monkeypatch, messages
):
    clock = FakeClock(step=6)
    monkeypatch.setattr(se, "time", clock)
    obj = make(stat_timer_secs=10)

    run_writer(
        obj,
        line(inverters={"I1": device(Pac=1)}),
        line(inverters={"I1": device(Pac=2)}),
    )

    stats = [m for m in messages(logging.INFO) if "Data points written" in m]
    assert stats == ["Data points written to DB: 1"]


def test_without_a_stat_timer_the_number_of_points_is_not_logged(
    se, make, monkeypatch, messages
):
    monkeypatch.setattr(se, "time", FakeClock(step=1000))

    run_writer(make(), *[line(inverters={"I1": device(Pac=1)})] * 3)

    assert not [m for m in messages() if "Data points written" in m]


# --- logger ------------------------------------------------------------------


def run_logger(obj, *lines):
    obj.logger_queue = FakeQueue(*lines)
    obj.shutdown.set()
    obj.logger()


def test_the_logger_writes_every_line_unchanged(make, workdir):
    log = workdir / "semonitor.log"

    run_logger(make(log_path=str(log)), '{"a": 1}\n', '{"b": 2}\n')

    assert log.read_text() == '{"a": 1}\n{"b": 2}\n'


def test_the_logger_extends_an_existing_log(make, workdir):
    log = workdir / "semonitor.log"
    log.write_text("earlier\n")

    run_logger(make(log_path=str(log)), "later\n")

    assert log.read_text() == "earlier\nlater\n"


def test_the_logger_flushes_each_line(make, workdir):
    log = workdir / "semonitor.log"
    obj = make(log_path=str(log))
    seen: ClassVar[list] = []
    obj.logger_queue = FakeQueue("one\n", "two\n")
    original_get = obj.logger_queue.get

    def get(timeout=None):
        seen.append(log.read_text() if log.exists() else None)
        return original_get(timeout)

    obj.logger_queue.get = get
    obj.shutdown.set()

    obj.logger()

    assert seen[:3] == ["", "one\n", "one\ntwo\n"]


def test_a_log_that_cannot_be_opened_is_logged_and_ends_the_logger(
    make, workdir, messages
):
    run_logger(make(log_path=str(workdir / "missing" / "semonitor.log")), "x\n")

    assert any("Error opening" in m for m in messages(logging.ERROR))


def test_the_logger_does_not_rotate_without_a_maximum_size(make, workdir):
    log = workdir / "semonitor.log"

    run_logger(make(log_path=str(log), max_log_size=0), "x" * 5000 + "\n")

    assert [path.name for path in workdir.iterdir()] == ["semonitor.log"]


def test_the_logger_does_not_rotate_below_the_maximum_size(make, workdir):
    log = workdir / "semonitor.log"

    run_logger(make(log_path=str(log), max_log_size=100), "x" * 10 + "\n")

    assert [path.name for path in workdir.iterdir()] == ["semonitor.log"]


@pytest.fixture
def fixed_now(se, monkeypatch):
    class FixedDatetime(se.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2016, 1, 1, 12, 30, 0)

    monkeypatch.setattr(se, "datetime", FixedDatetime)


def test_a_log_over_the_maximum_size_is_compressed_and_started_again(
    make, workdir, fixed_now
):
    log = workdir / "semonitor.log"

    run_logger(
        make(log_path=str(log), max_log_size=10),
        "0123456789abc\n",
        "next line\n",
    )

    archive = workdir / f"semonitor-{FIXED_NOW_STAMP}.log.gz"
    assert gzip.decompress(archive.read_bytes()) == b"0123456789abc\n"
    assert log.read_text() == "next line\n"


def test_rotation_failing_is_logged_and_the_logging_goes_on(
    se, make, workdir, messages, monkeypatch
):
    log = workdir / "semonitor.log"
    obj = make(log_path=str(log), max_log_size=1)

    def broken():
        raise OSError("disk full")

    monkeypatch.setattr(obj, "rotate_log", broken)

    run_logger(obj, "first\n", "second\n")

    assert log.read_text() == "first\nsecond\n"
    assert any(
        "Failed to rotate" in m and "disk full" in m
        for m in messages(logging.ERROR)
    )


# --- rotate_log -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "archive"),
    [
        ("semonitor.log", f"semonitor-{FIXED_NOW_STAMP}.log.gz"),
        ("semonitor.data.log", f"semonitor.data-{FIXED_NOW_STAMP}.log.gz"),
        ("semonitor", f"semonitor-{FIXED_NOW_STAMP}.gz"),
    ],
)
def test_the_archive_is_named_after_the_log_with_the_time_before_the_extension(
    make, workdir, fixed_now, name, archive
):
    log = workdir / name
    log.write_text("content\n")

    make(log_path=str(log)).rotate_log()

    assert (workdir / archive).is_file()
    assert gzip.decompress((workdir / archive).read_bytes()) == b"content\n"
    assert log.read_text() == ""


@pytest.mark.xfail(strict=True, reason="Issue #28")
def test_a_dot_in_the_directory_is_not_taken_for_an_extension(
    make, workdir, fixed_now
):
    directory = workdir / "var.log.d"
    directory.mkdir()
    log = directory / "semonitor"
    log.write_text("content\n")

    make(log_path=str(log)).rotate_log()

    assert (directory / f"semonitor-{FIXED_NOW_STAMP}.gz").is_file()


def test_rotating_a_log_that_does_not_exist_is_an_error(
    make, workdir, fixed_now
):
    with pytest.raises(FileNotFoundError):
        make(log_path=str(workdir / "missing.log")).rotate_log()
