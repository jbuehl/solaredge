import io
import json
from pathlib import Path
import pickle
import runpy
import socket
import struct
import sys
import time
import types
from typing import ClassVar

import pytest

CONVERSION = Path(__file__).resolve().parent.parent / "conversion"
SCRIPT = CONVERSION / "pickle2graphite.py"


class FakeSocket:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.address = None
        self.timeout = None
        self.sent = []
        self.closed = False
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
    # The script sets a process wide default timeout.
    previous = socket.getdefaulttimeout()
    yield state
    socket.setdefaulttimeout(previous)


def load(monkeypatch, *args, stdin="", run_name="pickle2graphite"):
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


def names_and_values(batch):
    return [(name, value) for name, (_, value) in batch]


def device(**attrs):
    # pickle2graphite needs a Date and a Time. Their value is filler.
    return {"Date": "2016-01-01", "Time": "12:37:48", **attrs}


def line(**sections):
    data = {"events": {}, "inverters": {}, "optimizers": {}}
    data.update(sections)
    return json.dumps(data) + "\n"


# --- Pickle2Graphite ---------------------------------------------------------


@pytest.fixture
def pickle2graphite(env, monkeypatch):
    return load(monkeypatch)["Pickle2Graphite"]


def test_it_is_a_list_of_nested_tuples_as_carbon_expects(pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1.5)}}, base="")

    assert isinstance(batch, list)
    assert names_and_values(batch) == [("inverters.I1.Pac", "1.5")]


def test_the_base_is_used_as_given_in_front_of_the_name(pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1)}}, base="solar.")

    assert batch[0][0] == "solar.inverters.I1.Pac"


def test_every_numeric_attribute_of_every_device_is_added(pickle2graphite):
    data = {
        "inverters": {"I1": device(Pac=1, Vac=2), "I2": device(Pac=3)},
        "optimizers": {"O1": device(Vmod=4)},
    }

    batch = pickle2graphite(data, base="")

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
def test_attributes_that_are_not_numbers_are_left_out(pickle2graphite, attrs):
    assert (
        pickle2graphite({"inverters": {"I1": device(**attrs)}}, base="") == []
    )


def test_date_and_time_are_not_metrics(pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1)}}, base="")

    assert [name for name, _ in batch] == ["inverters.I1.Pac"]


def test_the_value_is_a_string_and_the_timestamp_a_number(pickle2graphite):
    ((_, (stamp, value)),) = pickle2graphite(
        {"inverters": {"I1": device(Pac=12)}}, base=""
    )

    assert value == "12"
    assert isinstance(stamp, (int, float))


def test_a_missing_time_is_logged_and_replaced_by_the_epoch(env, monkeypatch):
    namespace = load(monkeypatch)

    batch = namespace["Pickle2Graphite"](
        {"inverters": {"I1": {"Date": "2016-01-01", "Pac": 1}}}, base=""
    )

    assert batch == [("inverters.I1.Pac", (61.0, "1"))]
    assert "Date or Time" in env.syslog[0]


def test_nothing_in_gives_an_empty_batch(pickle2graphite):
    assert pickle2graphite({}, base="") == []
    assert pickle2graphite({"inverters": {}}, base="") == []


def test_send_prefixes_the_pickled_list_with_its_length(env, pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1.5)}}, base="")
    connection = FakeSocket()

    batch.send(connection)

    (message,) = connection.sent
    assert names_and_values(unpack(message)) == [("inverters.I1.Pac", "1.5")]


def test_send_sends_a_plain_list_not_the_subclass(env, pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1)}}, base="")
    connection = FakeSocket()

    batch.send(connection)

    assert type(unpack(connection.sent[0])) is list


def test_send_waits_afterwards_to_not_swamp_carbon(env, pickle2graphite):
    batch = pickle2graphite({"inverters": {"I1": device(Pac=1)}}, base="")

    batch.send(FakeSocket())

    assert len(env.sleeps) == 1
    assert env.sleeps[0] > 0


# --- getJsonStr --------------------------------------------------------------


class Source:
    def __init__(self, *results):
        self.results = list(results)

    def readline(self):
        return self.results.pop(0) if self.results else ""


def test_get_json_str_reads_a_line(env, monkeypatch):
    get = load(monkeypatch)["getJsonStr"]

    assert get(Source("{}\n"), following=False) == "{}\n"


def test_get_json_str_gives_an_empty_string_at_the_end_when_not_following(
    env, monkeypatch
):
    get = load(monkeypatch)["getJsonStr"]

    assert get(Source(), following=False) == ""
    assert env.sleeps == []


def test_get_json_str_waits_for_more_data_when_following(env, monkeypatch):
    get = load(monkeypatch)["getJsonStr"]

    assert get(Source("", "", "{}\n"), following=True) == "{}\n"
    assert len(env.sleeps) == 2


def test_get_json_str_does_not_wait_when_there_already_is_data(
    env, monkeypatch
):
    get = load(monkeypatch)["getJsonStr"]

    get(Source("{}\n"), following=True)

    assert env.sleeps == []


# --- log ---------------------------------------------------------------------


def test_log_joins_the_arguments_with_spaces(env, monkeypatch):
    log = load(monkeypatch)["log"]

    log("one", 2, ["three"])

    assert env.syslog == ["one 2 ['three'] "]


# --- command line ------------------------------------------------------------


def test_defaults_are_localhost_and_the_carbon_pickle_port(env, monkeypatch):
    connection = run_main(monkeypatch)

    assert connection.address == ("localhost", 2004)
    assert connection.closed


def test_host_and_port_can_be_changed(env, monkeypatch):
    connection = run_main(monkeypatch, "-h", "carbon.lan", "-p", "12004")

    assert connection.address == ("carbon.lan", 12004)


def test_connecting_to_a_dead_graphite_times_out_after_ten_seconds(
    env, monkeypatch
):
    run_main(monkeypatch)

    assert socket.getdefaulttimeout() == 10.0


def test_the_base_gets_a_dot_appended(env, monkeypatch):
    connection = run_main(
        monkeypatch, "-b", "home", stdin=line(inverters={"I1": device(Pac=1)})
    )

    assert unpack(connection.sent[0])[0][0] == "home.inverters.I1.Pac"


def test_every_line_is_sent_as_its_own_batch(env, monkeypatch):
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
