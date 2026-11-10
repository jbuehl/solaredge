import io
import json
from pathlib import Path
import re
import runpy
import socket
import sys
import time
import types
from typing import ClassVar

import pytest

CONVERSION = Path(__file__).resolve().parent.parent / "conversion"
SCRIPT = CONVERSION / "se2graphite.py"
METRIC = re.compile(
    rb"^(?P<name>\S+) (?P<value>\S+) (?P<stamp>\d+(?:\.\d+)?)\n$"
)


class FakeSocket:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.address = None
        self.sent = []
        self.closed = False
        self.timeout = None
        FakeSocket.instances.append(self)

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        self.address = address

    def send(self, data):
        if isinstance(data, str):
            raise TypeError("a bytes-like object is required, not 'str'")
        self.sent.append(data)
        return len(data)

    sendall = send

    def close(self):
        self.closed = True


class Env:
    def __init__(self):
        self.syslog = []
        self.sleeps = []


@pytest.fixture
def env(monkeypatch):
    FakeSocket.instances = []
    state = Env()
    fake_syslog = types.ModuleType("syslog")
    fake_syslog.syslog = state.syslog.append
    monkeypatch.setitem(sys.modules, "syslog", fake_syslog)
    monkeypatch.setattr(socket, "socket", FakeSocket)
    monkeypatch.setattr(time, "sleep", state.sleeps.append)
    monkeypatch.syspath_prepend(str(CONVERSION))
    monkeypatch.delitem(sys.modules, "common", raising=False)
    return state


def run_se2graphite(monkeypatch, *args, stdin=""):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    runpy.run_path(str(SCRIPT), run_name="__main__")
    (connection,) = FakeSocket.instances
    return connection


def metrics(connection):
    parsed = []
    for data in connection.sent:
        match = METRIC.match(data)
        assert match, data
        parsed.append(
            (
                match["name"].decode(),
                match["value"].decode(),
                float(match["stamp"]),
            )
        )
    return parsed


def names_and_values(connection):
    return [(name, value) for name, value, _ in metrics(connection)]


def device(**attrs):
    # se2graphite needs a Date and a Time. Their value is filler, the
    # timestamps have their own tests.
    return {"Date": "2016-01-01", "Time": "12:37:48", **attrs}


def line(**sections):
    data = {"events": {}, "inverters": {}, "optimizers": {}}
    data.update(sections)
    return json.dumps(data) + "\n"


# --- command line ------------------------------------------------------------


def test_connects_to_the_graphite_plaintext_port_on_localhost_by_default(
    env, monkeypatch
):
    connection = run_se2graphite(monkeypatch)

    assert connection.address == ("localhost", 2003)
    assert connection.closed
    assert connection.sent == []


def test_host_and_port_can_be_changed(env, monkeypatch):
    connection = run_se2graphite(
        monkeypatch, "-h", "graphite.lan", "-p", "2203"
    )

    assert connection.address == ("graphite.lan", 2203)


def test_a_non_numeric_port_is_an_error(env, monkeypatch):
    with pytest.raises(ValueError):
        run_se2graphite(monkeypatch, "-p", "plaintext")


def test_unknown_options_are_an_error(env, monkeypatch):
    with pytest.raises(Exception, match="-z"):
        run_se2graphite(monkeypatch, "-z")


# --- metrics -----------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_every_numeric_attribute_becomes_a_metric(env, monkeypatch):
    stdin = line(inverters={"I1": device(Pac=1.5, Vac=240)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert names_and_values(connection) == [
        ("inverters.I1.Pac", "1.5"),
        ("inverters.I1.Vac", "240"),
    ]


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_each_metric_is_one_newline_terminated_message(env, monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1.5)})
    )

    assert len(connection.sent) == 1
    assert connection.sent[0].endswith(b"\n")
    assert connection.sent[0].count(b"\n") == 1


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_the_base_is_prepended_with_a_dot(env, monkeypatch):
    connection = run_se2graphite(
        monkeypatch,
        "-b",
        "home.solar",
        stdin=line(inverters={"I1": device(Pac=1)}),
    )

    assert metrics(connection)[0][0] == "home.solar.inverters.I1.Pac"


@pytest.mark.parametrize(
    "attrs",
    [
        {"Name": "text"},
        {"Name": ""},
        {"Undeciphered_data": "53 6f 6c"},
        {"Pac": float("nan")},
        pytest.param(
            {"Flag": None},
            marks=pytest.mark.xfail(strict=True, reason="Issue #24"),
        ),
        pytest.param(
            {"List": [1]},
            marks=pytest.mark.xfail(strict=True, reason="Issue #24"),
        ),
    ],
)
def test_attributes_that_are_not_numbers_are_not_sent(env, monkeypatch, attrs):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(**attrs)})
    )

    assert connection.sent == []


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_date_and_time_are_not_sent_as_metrics(env, monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1)})
    )

    assert [name for name, *_ in metrics(connection)] == ["inverters.I1.Pac"]


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_numeric_strings_are_sent(env, monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac="12.5")})
    )

    assert names_and_values(connection) == [("inverters.I1.Pac", "12.5")]


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_every_line_and_device_is_sent_in_order(env, monkeypatch):
    stdin = line(
        inverters={"I1": device(Pac=1)}, optimizers={"O1": device(Vmod=2)}
    )
    stdin += line(inverters={"I2": device(Pac=3)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert names_and_values(connection) == [
        ("inverters.I1.Pac", "1"),
        ("optimizers.O1.Vmod", "2"),
        ("inverters.I2.Pac", "3"),
    ]


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_it_sleeps_between_metrics_instead_of_flooding_graphite(
    env, monkeypatch
):
    run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1, Vac=2, Iac=3)})
    )

    assert len(env.sleeps) == 3
    assert all(0 < delay <= 1 for delay in env.sleeps)


# --- timestamps --------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #15")
@pytest.mark.parametrize(
    ("date", "time_", "epoch"),
    [
        ("2016-01-01", "12:37:48", 1451651868),
        ("1970-01-02", "00:00:00", 86400),
        ("2038-01-19", "03:14:08", 2**31),
        ("2020-02-29", "23:59:59", 1583020799),
    ],
)
def test_date_and_time_are_the_timestamp_in_local_time(
    env, monkeypatch, date, time_, epoch
):
    stdin = line(inverters={"I1": {"Date": date, "Time": time_, "Pac": 1}})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert metrics(connection)[0][2] == epoch


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_the_timestamp_follows_the_local_timezone_including_dst(
    env, monkeypatch
):
    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    time.tzset()
    try:
        summer = line(
            inverters={
                "I1": {"Date": "2016-07-01", "Time": "12:00:00", "Pac": 1}
            }
        )
        winter = line(
            inverters={
                "I1": {"Date": "2016-01-01", "Time": "12:00:00", "Pac": 1}
            }
        )

        connection = run_se2graphite(monkeypatch, stdin=summer + winter)
    finally:
        monkeypatch.setenv("TZ", "UTC0")
        time.tzset()

    summer_epoch, winter_epoch = (stamp for *_, stamp in metrics(connection))
    # 12:00 local is 10:00 UTC in summer, 11:00 UTC in winter
    assert summer_epoch == 1467367200
    assert winter_epoch == 1451646000


@pytest.mark.xfail(strict=True, reason="Issue #15")
def test_a_missing_time_is_logged_and_replaced_by_the_epoch(env, monkeypatch):
    stdin = line(inverters={"I1": {"Date": "2016-01-01", "Pac": 1}})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert env.syslog
    assert "Date or Time" in env.syslog[0]
    assert metrics(connection) == [("inverters.I1.Pac", "1", 61.0)]


@pytest.mark.xfail(strict=True, reason="Issue #25")
def test_a_badly_formatted_date_is_logged_not_fatal(env, monkeypatch):
    stdin = line(
        inverters={"I1": {"Date": "01/02/2016", "Time": "12:00:00", "Pac": 1}}
    )

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert env.syslog
    assert len(connection.sent) == 1


@pytest.mark.xfail(strict=True, reason="Issue #26")
def test_invalid_json_is_logged_and_the_rest_is_still_sent(env, monkeypatch):
    stdin = "this is not json\n" + line(inverters={"I1": device(Pac=1)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert len(connection.sent) == 1
    assert env.syslog
