import io
import json
import pickle
import re
import runpy
import socket
import struct
import sys
import time
import types
from pathlib import Path
from typing import ClassVar

import pytest

CLI = Path(__file__).resolve().parent.parent / "src" / "se"
SCRIPT = CLI / "se2graphite.py"
METRIC = re.compile(
    rb"^(?P<name>\S+) (?P<value>\S+) (?P<stamp>\d+(?:\.\d+)?)\n$"
)


class FakeSocket:
    instances: ClassVar[list] = []

    def __init__(self, *args, **_kwargs):
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
            msg = "a bytes-like object is required, not 'str'"
            raise TypeError(msg)
        self.sent.append(data)
        return len(data)

    sendall = send

    def close(self):
        self.closed = True


class Env:
    def __init__(self):
        self.syslog = []
        self.sleeps = []


@pytest.fixture(autouse=True)
def env(monkeypatch):
    FakeSocket.instances = []
    state = Env()
    fake_syslog = types.ModuleType("syslog")
    fake_syslog.syslog = state.syslog.append
    monkeypatch.setitem(sys.modules, "syslog", fake_syslog)
    monkeypatch.setattr(socket, "socket", FakeSocket)
    monkeypatch.setattr(time, "sleep", state.sleeps.append)
    # The pickle mode sets a process wide default timeout.
    previous = socket.getdefaulttimeout()
    yield state
    socket.setdefaulttimeout(previous)


def run_se2graphite(monkeypatch, *args, stdin=""):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "-t", *map(str, args)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    runpy.run_path(str(SCRIPT), run_name="__main__")
    (connection,) = FakeSocket.instances
    return connection


def text_metrics(connection):
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


def text_names_and_values(connection):
    return [(name, value) for name, value, _ in text_metrics(connection)]


def device(**attrs):
    # se2graphite needs a Date and a Time. Their value is filler, the
    # timestamps have their own tests.
    return {"Date": "2016-01-01", "Time": "12:37:48", **attrs}


def line(**sections):
    data = {"events": {}, "inverters": {}, "optimizers": {}}
    data.update(sections)
    return json.dumps(data) + "\n"


def load(monkeypatch, *args, stdin="", run_name="se2graphite"):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return runpy.run_path(str(SCRIPT), run_name=run_name)


def run_main(monkeypatch, *args, stdin=""):
    load(monkeypatch, *args, stdin=stdin, run_name="__main__")
    (connection,) = FakeSocket.instances
    return connection


def unpack(message):
    (length,) = struct.unpack("!L", message[:4])
    payload = message[4:]
    assert length == len(payload)
    return pickle.loads(payload)  # made by the script


def batch_names_and_values(batch):
    return [(name, value) for name, (_, value) in batch]


# --- command line (text) ---


def test_connects_to_the_graphite_plaintext_port_on_localhost_by_default(
    monkeypatch,
):
    connection = run_se2graphite(monkeypatch)

    assert connection.address == ("localhost", 2003)
    assert connection.closed
    assert connection.sent == []


def test_text_host_and_port_can_be_changed(monkeypatch):
    connection = run_se2graphite(
        monkeypatch, "-h", "graphite.lan", "-p", "2203"
    )

    assert connection.address == ("graphite.lan", 2203)


def test_a_non_numeric_port_is_an_error(monkeypatch):
    with pytest.raises(ValueError, match="plaintext"):
        run_se2graphite(monkeypatch, "-p", "plaintext")


def test_unknown_options_are_an_error(monkeypatch):
    with pytest.raises(Exception, match="-z"):
        run_se2graphite(monkeypatch, "-z")


def test_connecting_to_a_dead_graphite_times_out_after_ten_seconds_in_text(
    monkeypatch,
):
    run_se2graphite(monkeypatch)

    assert socket.getdefaulttimeout() == 10.0


# --- metrics (text) ---


def test_every_numeric_attribute_becomes_a_metric(monkeypatch):
    stdin = line(inverters={"I1": device(Pac=1.5, Vac=240)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert text_names_and_values(connection) == [
        ("inverters.I1.Pac", "1.5"),
        ("inverters.I1.Vac", "240"),
    ]


def test_each_metric_is_one_newline_terminated_message(monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1.5)})
    )

    assert len(connection.sent) == 1
    assert connection.sent[0].endswith(b"\n")
    assert connection.sent[0].count(b"\n") == 1


def test_the_base_is_prepended_with_a_dot(monkeypatch):
    connection = run_se2graphite(
        monkeypatch,
        "-b",
        "home.solar",
        stdin=line(inverters={"I1": device(Pac=1)}),
    )

    assert text_metrics(connection)[0][0] == "home.solar.inverters.I1.Pac"


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
def test_attributes_that_are_not_numbers_are_not_sent(monkeypatch, attrs):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(**attrs)})
    )

    assert connection.sent == []


def test_date_and_time_are_not_sent_as_metrics(monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1)})
    )

    assert [name for name, *_ in text_metrics(connection)] == [
        "inverters.I1.Pac"
    ]


def test_numeric_strings_are_sent(monkeypatch):
    connection = run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac="12.5")})
    )

    assert text_names_and_values(connection) == [("inverters.I1.Pac", "12.5")]


def test_every_line_and_device_is_sent_in_order(monkeypatch):
    stdin = line(
        inverters={"I1": device(Pac=1)}, optimizers={"O1": device(Vmod=2)}
    )
    stdin += line(inverters={"I2": device(Pac=3)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert text_names_and_values(connection) == [
        ("inverters.I1.Pac", "1"),
        ("optimizers.O1.Vmod", "2"),
        ("inverters.I2.Pac", "3"),
    ]


def test_it_sleeps_between_metrics_instead_of_flooding_graphite(
    env, monkeypatch
):
    run_se2graphite(
        monkeypatch, stdin=line(inverters={"I1": device(Pac=1, Vac=2, Iac=3)})
    )

    assert len(env.sleeps) == 3
    assert all(0 < delay <= 1 for delay in env.sleeps)


# --- timestamps (text) ---


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
    monkeypatch, date, time_, epoch
):
    stdin = line(inverters={"I1": {"Date": date, "Time": time_, "Pac": 1}})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert text_metrics(connection)[0][2] == epoch


def test_the_timestamp_follows_the_local_timezone_including_dst(monkeypatch):
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

    summer_epoch, winter_epoch = (
        stamp for *_, stamp in text_metrics(connection)
    )
    # 12:00 local is 10:00 UTC in summer, 11:00 UTC in winter
    assert summer_epoch == 1467367200
    assert winter_epoch == 1451646000


def test_a_missing_time_is_logged_and_replaced_by_the_epoch_in_text(
    env, monkeypatch
):
    stdin = line(inverters={"I1": {"Date": "2016-01-01", "Pac": 1}})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert env.syslog
    assert "Date or Time" in env.syslog[0]
    assert text_metrics(connection) == [("inverters.I1.Pac", "1", 61.0)]


@pytest.mark.xfail(strict=True, reason="Issue #25")
def test_a_badly_formatted_date_is_logged_not_fatal(env, monkeypatch):
    stdin = line(
        inverters={"I1": {"Date": "01/02/2016", "Time": "12:00:00", "Pac": 1}}
    )

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert env.syslog
    assert len(connection.sent) == 1


def test_invalid_json_is_logged_and_the_rest_is_still_sent(env, monkeypatch):
    stdin = "this is not json\n" + line(inverters={"I1": device(Pac=1)})

    connection = run_se2graphite(monkeypatch, stdin=stdin)

    assert len(connection.sent) == 1
    assert env.syslog


# --- Metrics ---


@pytest.fixture
def metrics_class(request, monkeypatch):
    request.getfixturevalue("env")
    return load(monkeypatch)["Metrics"]


def test_it_is_a_list_of_nested_tuples_as_carbon_expects(metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1.5)}}, base="")

    assert isinstance(batch, list)
    assert batch_names_and_values(batch) == [("inverters.I1.Pac", "1.5")]


def test_the_base_is_used_as_given_in_front_of_the_name(metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1)}}, base="solar.")

    assert batch[0][0] == "solar.inverters.I1.Pac"


def test_every_numeric_attribute_of_every_device_is_added(metrics_class):
    data = {
        "inverters": {"I1": device(Pac=1, Vac=2), "I2": device(Pac=3)},
        "optimizers": {"O1": device(Vmod=4)},
    }

    batch = metrics_class(data, base="")

    assert sorted(name for name, _ in batch) == [
        "inverters.I1.Pac",
        "inverters.I1.Vac",
        "inverters.I2.Pac",
        "optimizers.O1.Vmod",
    ]


@pytest.mark.parametrize(
    "attrs",
    [
        {"Name": "text"},
        {"Undeciphered_data": "53 6f 6c"},
        {"Pac": float("nan")},
        pytest.param(
            {"Pac": None},
            marks=pytest.mark.xfail(strict=True, reason="Issue #24"),
        ),
    ],
)
def test_attributes_that_are_not_numbers_are_left_out(metrics_class, attrs):
    assert metrics_class({"inverters": {"I1": device(**attrs)}}, base="") == []


def test_date_and_time_are_not_metrics(metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1)}}, base="")

    assert [name for name, _ in batch] == ["inverters.I1.Pac"]


def test_the_value_is_a_string_and_the_timestamp_a_number(metrics_class):
    ((_, (stamp, value)),) = metrics_class(
        {"inverters": {"I1": device(Pac=12)}}, base=""
    )

    assert value == "12"
    assert isinstance(stamp, (int, float))


def test_a_missing_time_is_logged_and_replaced_by_the_epoch_in_a_batch(
    env, monkeypatch
):
    namespace = load(monkeypatch)

    batch = namespace["Metrics"](
        {"inverters": {"I1": {"Date": "2016-01-01", "Pac": 1}}}, base=""
    )

    assert batch == [("inverters.I1.Pac", (61.0, "1"))]
    assert "Date or Time" in env.syslog[0]


def test_nothing_in_gives_an_empty_batch(metrics_class):
    assert metrics_class({}, base="") == []
    assert metrics_class({"inverters": {}}, base="") == []


def test_send_pickle_prefixes_the_pickled_list_with_its_length(metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1.5)}}, base="")
    connection = FakeSocket()

    batch.send_pickle(connection)

    (message,) = connection.sent
    assert batch_names_and_values(unpack(message)) == [
        ("inverters.I1.Pac", "1.5")
    ]


def test_send_pickle_sends_a_plain_list_not_the_subclass(metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1)}}, base="")
    connection = FakeSocket()

    batch.send_pickle(connection)

    assert type(unpack(connection.sent[0])) is list


def test_send_pickle_waits_afterwards_to_not_swamp_carbon(env, metrics_class):
    batch = metrics_class({"inverters": {"I1": device(Pac=1)}}, base="")

    batch.send_pickle(FakeSocket())

    assert len(env.sleeps) == 1
    assert env.sleeps[0] > 0


# --- get_json_str ---


class Source:
    def __init__(self, *results):
        self.results = list(results)

    def readline(self):
        return self.results.pop(0) if self.results else ""


def test_get_json_str_reads_a_line(monkeypatch):
    get = load(monkeypatch)["get_json_str"]

    assert get(Source("{}\n"), following=False) == "{}\n"


def test_get_json_str_gives_an_empty_string_at_the_end_when_not_following(
    env, monkeypatch
):
    get = load(monkeypatch)["get_json_str"]

    assert get(Source(), following=False) == ""
    assert env.sleeps == []


def test_get_json_str_waits_for_more_data_when_following(env, monkeypatch):
    get = load(monkeypatch)["get_json_str"]

    assert get(Source("", "", "{}\n"), following=True) == "{}\n"
    assert len(env.sleeps) == 2


def test_get_json_str_does_not_wait_when_there_already_is_data(
    env, monkeypatch
):
    get = load(monkeypatch)["get_json_str"]

    get(Source("{}\n"), following=True)

    assert env.sleeps == []


# --- log ---


def test_log_joins_the_arguments_with_spaces(env, monkeypatch):
    log = load(monkeypatch)["log"]

    log("one", 2, ["three"])

    assert env.syslog == ["one 2 ['three'] "]


# --- command line ---


def test_defaults_are_localhost_and_the_carbon_pickle_port(monkeypatch):
    connection = run_main(monkeypatch)

    assert connection.address == ("localhost", 2004)
    assert connection.closed


def test_pickle_host_and_port_can_be_changed(monkeypatch):
    connection = run_main(monkeypatch, "-h", "carbon.lan", "-p", "12004")

    assert connection.address == ("carbon.lan", 12004)


def test_connecting_to_a_dead_graphite_times_out_after_ten_seconds(monkeypatch):
    run_main(monkeypatch)

    assert socket.getdefaulttimeout() == 10.0


def test_the_base_gets_a_dot_appended(monkeypatch):
    connection = run_main(
        monkeypatch, "-b", "home", stdin=line(inverters={"I1": device(Pac=1)})
    )

    assert unpack(connection.sent[0])[0][0] == "home.inverters.I1.Pac"


def test_every_line_is_sent_as_its_own_batch(monkeypatch):
    stdin = line(inverters={"I1": device(Pac=1)}) + line(
        inverters={"I1": device(Pac=2)}
    )

    connection = run_main(monkeypatch, stdin=stdin)

    assert [unpack(message)[0][1][1] for message in connection.sent] == [
        "1",
        "2",
    ]


def test_a_line_that_is_not_json_is_logged_and_skipped(env, monkeypatch):
    stdin = "garbage\n" + line(inverters={"I1": device(Pac=1)})

    connection = run_main(monkeypatch, stdin=stdin)

    assert len(connection.sent) == 1
    assert any("garbage" in message for message in env.syslog)
