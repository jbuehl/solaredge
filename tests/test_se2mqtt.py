import json
import runpy
import sys
import time
import types
from pathlib import Path
from typing import ClassVar

import pytest

CONVERSION = Path(__file__).resolve().parent.parent / "conversion"
SCRIPT = CONVERSION / "se2MQTT.py"
ALL_OPTIONS = (
    "-c",
    "client",
    "-u",
    "user",
    "-p",
    "secret",
    "-s",
    "broker",
    "-t",
    "/ha/solar",
)


class InputExhausted(BaseException):
    pass


class Input:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        if not self.lines:
            raise InputExhausted
        return self.lines.pop(0)


class FakeClient:
    instances: ClassVar[list] = []
    fail_on = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls = []
        FakeClient.instances.append(self)

    def username_pw_set(self, user, password=None):
        self.calls.append(("username_pw_set", user, password))

    def connect(self, host, *_args, **_kwargs):
        self.calls.append(("connect", host))
        if FakeClient.fail_on == "connect":
            msg = "broker is down"
            raise ConnectionRefusedError(msg)

    def publish(self, topic, payload=None, *_args, **_kwargs):
        self.calls.append(("publish", topic, payload))
        if FakeClient.fail_on == "publish":
            msg = "publish failed"
            raise OSError(msg)

    def disconnect(self):
        self.calls.append(("disconnect",))

    def names(self):
        return [call[0] for call in self.calls]


@pytest.fixture(autouse=True)
def broker(monkeypatch):
    FakeClient.instances = []
    FakeClient.fail_on = None
    client = types.ModuleType("paho.mqtt.client")
    client.Client = FakeClient
    mqtt = types.ModuleType("paho.mqtt")
    mqtt.client = client
    paho = types.ModuleType("paho")
    paho.mqtt = mqtt
    monkeypatch.setitem(sys.modules, "paho", paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", client)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    return FakeClient


def run_se2mqtt(monkeypatch, lines, *args):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *args])
    monkeypatch.setattr(sys, "stdin", Input(lines))
    with pytest.raises(InputExhausted):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    return FakeClient.instances


def published(clients):
    return [
        json.loads(call[2])
        for client in clients
        for call in client.calls
        if call[0] == "publish"
    ]


def inverter(**attrs):
    return {"Eac": 5.0, "Pac": 100.0, "Vac": 240.0, **attrs}


def line(inverters=None, optimizers=None, events=None):
    return (
        json.dumps(
            {
                "events": events or {},
                "inverters": inverters or {},
                "optimizers": optimizers or {},
            }
        )
        + "\n"
    )


# --- connecting and publishing -----------------------------------------------


def test_the_state_is_published_to_the_topic_with_the_given_credentials(
    monkeypatch,
):
    clients = run_se2mqtt(monkeypatch, [line({"I1": inverter()})], *ALL_OPTIONS)

    (client,) = clients
    assert client.kwargs.get("client_id") == "client"
    assert client.calls[0] == ("username_pw_set", "user", "secret")
    assert ("connect", "broker") in client.calls
    assert client.calls[-2][:2] == ("publish", "/ha/solar")
    assert client.names()[-1] == "disconnect"


def test_the_payload_is_json_with_the_inverters_and_optimizers(monkeypatch):
    clients = run_se2mqtt(
        monkeypatch,
        [line({"I1": inverter()}, {"O1": {"Vmod": 30.0}})],
        *ALL_OPTIONS,
    )

    assert published(clients) == [
        {"inverters": {"I1": inverter()}, "optimizers": {"O1": {"Vmod": 30.0}}}
    ]


def test_every_line_is_published_as_the_state_so_far(monkeypatch):
    clients = run_se2mqtt(
        monkeypatch,
        [
            line({"I1": inverter(Pac=1.0)}),
            line({"I2": inverter(Pac=2.0)}),
            line({"I1": inverter(Pac=3.0)}),
        ],
        *ALL_OPTIONS,
    )

    states = published(clients)
    assert [sorted(state["inverters"]) for state in states] == [
        ["I1"],
        ["I1", "I2"],
        ["I1", "I2"],
    ]
    assert states[2]["inverters"]["I1"]["Pac"] == 3.0
    assert states[2]["inverters"]["I2"]["Pac"] == 2.0


def test_the_connection_is_made_again_for_each_message(monkeypatch):
    clients = run_se2mqtt(
        monkeypatch,
        [line({"I1": inverter()}), line({"I1": inverter()})],
        *ALL_OPTIONS,
    )

    assert len(clients) == 2
    assert all(client.names().count("disconnect") == 1 for client in clients)


# --- events ------------------------------------------------------------------


def test_an_event_zeroes_the_energy_and_power_of_all_inverters(monkeypatch):
    clients = run_se2mqtt(
        monkeypatch,
        [
            line({"I1": inverter(), "I2": inverter()}),
            line(events={"I1": {"Type": 1}}),
        ],
        *ALL_OPTIONS,
    )

    state = published(clients)[1]["inverters"]
    for ident in ("I1", "I2"):
        assert state[ident]["Eac"] == 0.0
        assert state[ident]["Pac"] == 0.0
        assert state[ident]["Vac"] == 240.0


def test_without_an_event_nothing_is_zeroed(monkeypatch):
    clients = run_se2mqtt(monkeypatch, [line({"I1": inverter()})], *ALL_OPTIONS)

    assert published(clients)[0]["inverters"]["I1"]["Pac"] == 100.0


# --- failures ----------------------------------------------------------------


@pytest.mark.parametrize("failing_call", ["connect", "publish"])
def test_a_broker_that_fails_is_reported_and_does_not_stop_the_converter(
    monkeypatch, capsys, failing_call
):
    FakeClient.fail_on = failing_call

    clients = run_se2mqtt(
        monkeypatch,
        [line({"I1": inverter()}), line({"I1": inverter()})],
        *ALL_OPTIONS,
    )

    assert len(clients) == 2
    assert "MQTT Exception" in capsys.readouterr().out


def test_invalid_json_is_an_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *ALL_OPTIONS])
    monkeypatch.setattr(sys, "stdin", Input(["not json\n"]))

    with pytest.raises(ValueError, match="Expecting value"):
        runpy.run_path(str(SCRIPT), run_name="__main__")


# Without -t (or the others) there is nowhere to publish to. This has to be
# reported, and not end in a NameError after the first message was read.
@pytest.mark.xfail(strict=True, reason="Issue #22")
def test_the_options_are_all_required_to_publish(monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "-c", "client"])
    monkeypatch.setattr(sys, "stdin", Input([line({"I1": inverter()})]))

    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert exit_.value.code not in (0, None)
