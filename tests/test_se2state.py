import json
from pathlib import Path
import runpy
import sys
import time

import pytest

CONVERSION = Path(__file__).resolve().parent.parent / "conversion"
SCRIPT = CONVERSION / "se2state.py"


class InputExhausted(BaseException):
    pass


class Input:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        if not self.lines:
            raise InputExhausted
        return self.lines.pop(0)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def run_se2state(monkeypatch, lines, *args):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdin", Input(lines))
    with pytest.raises(InputExhausted):
        runpy.run_path(str(SCRIPT), run_name="__main__")


def read_state(path):
    return json.loads(Path(path).read_text())


def inverter(**attrs):
    return {
        "Eac": 5.0,
        "Eday": 10.0,
        "Etot": 1000.0,
        "Pac": 100.0,
        "Temp": 30.0,
        "Vac": 240.0,
        **attrs,
    }


def optimizer(**attrs):
    return {"Imod": 2.0, "Temp": 40.0, "Vmod": 30.0, "Vopt": 31.0, **attrs}


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


# --- initializing ------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #19")
def test_initializing_writes_a_zeroed_state_before_any_input(
    workdir, monkeypatch
):
    run_se2state(monkeypatch, [], "-i", "I1,I2", "-o", "state.json")

    state = read_state(workdir / "state.json")
    zero = {
        "Vac": 0.0,
        "Pac": 0.0,
        "Eac": 0.0,
        "Eday": 0.0,
        "Etot": 0.0,
        "Temp": 0.0,
    }
    assert state["inverters"]["stats"] == zero
    assert state["inverters"]["I1"] == zero
    assert state["inverters"]["I2"] == zero
    assert state["optimizers"] == {"stats": {"Temp": 0.0}}


def test_initializing_replaces_an_existing_state(workdir, monkeypatch):
    (workdir / "state.json").write_text(
        json.dumps({"inverters": {"stats": {"Eday": 99.0}}, "optimizers": {}})
    )

    run_se2state(monkeypatch, [], "-i", "I1", "-o", "state.json")

    assert (
        read_state(workdir / "state.json")["inverters"]["stats"]["Eday"] == 0.0
    )


def test_without_initializing_an_existing_state_is_continued(
    workdir, monkeypatch
):
    (workdir / "state.json").write_text(
        json.dumps(
            {
                "inverters": {
                    "stats": {
                        "Eday": 50.0,
                        "Vac": 0,
                        "Pac": 0,
                        "Eac": 0,
                        "Etot": 0,
                        "Temp": 0,
                    }
                },
                "optimizers": {"stats": {"Temp": 0.0}},
            }
        )
    )

    run_se2state(
        monkeypatch, [line({"I1": inverter(Eday=10.0)})], "-o", "state.json"
    )

    # Eday of the stats never goes down
    assert (
        read_state(workdir / "state.json")["inverters"]["stats"]["Eday"] == 50.0
    )


@pytest.mark.xfail(strict=True, reason="Issue #18")
def test_without_initializing_a_missing_state_is_started_empty(
    workdir, monkeypatch
):
    run_se2state(monkeypatch, [line({"I1": inverter()})], "-o", "state.json")

    assert read_state(workdir / "state.json")["inverters"]["I1"] == inverter()


@pytest.mark.xfail(strict=True, reason="Issue #23")
def test_the_output_file_is_required(workdir, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "-i", "I1"])
    monkeypatch.setattr(sys, "stdin", Input([]))

    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert exit_.value.code not in (0, None)


# --- updating the state ------------------------------------------------------


def test_devices_are_added_to_the_state_and_updated(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [
            line({"I1": inverter(Pac=1.0)}, {"O1": optimizer()}),
            line({"I1": inverter(Pac=2.0), "I2": inverter(Pac=3.0)}),
        ],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    state = read_state(workdir / "state.json")
    assert state["inverters"]["I1"]["Pac"] == 2.0
    assert state["inverters"]["I2"]["Pac"] == 3.0
    assert "O1" in state["optimizers"]


def test_the_state_file_is_written_after_every_line(workdir, monkeypatch):
    path = workdir / "state.json"
    seen = []
    original = Input.readline

    def readline(self):
        if path.exists():
            seen.append(read_state(path)["inverters"].get("I1", {}).get("Pac"))
        return original(self)

    monkeypatch.setattr(Input, "readline", readline)

    run_se2state(
        monkeypatch,
        [line({"I1": inverter(Pac=1.0)}), line({"I1": inverter(Pac=2.0)})],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    assert seen[1:] == [1.0, 2.0]


# --- statistics --------------------------------------------------------------


def test_the_statistics_sum_or_average_over_the_inverters(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [
            line(
                {
                    "I1": inverter(
                        Vac=240.0, Pac=100.0, Eac=1.0, Etot=1000.0, Temp=30.0
                    ),
                    "I2": inverter(
                        Vac=230.0, Pac=200.0, Eac=2.0, Etot=2000.0, Temp=40.0
                    ),
                }
            )
        ],
        "-i",
        "I1,I2",
        "-o",
        "state.json",
    )

    stats = read_state(workdir / "state.json")["inverters"]["stats"]
    assert stats["Vac"] == pytest.approx(235.0)
    assert stats["Pac"] == pytest.approx(300.0)
    assert stats["Eac"] == pytest.approx(3.0)
    assert stats["Etot"] == pytest.approx(3000.0)
    assert stats["Temp"] == pytest.approx(35.0)


def test_the_stats_entry_is_not_counted_as_a_device(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [line({"I1": inverter(Vac=240.0, Pac=100.0)})],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    stats = read_state(workdir / "state.json")["inverters"]["stats"]
    assert stats["Vac"] == pytest.approx(240.0)
    assert stats["Pac"] == pytest.approx(100.0)


def test_eday_of_the_statistics_only_increases(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [
            line({"I1": inverter(Eday=10.0)}),
            line({"I1": inverter(Eday=4.0)}),
        ],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    assert (
        read_state(workdir / "state.json")["inverters"]["stats"]["Eday"] == 10.0
    )


def test_eday_of_the_statistics_follows_an_increase(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [line({"I1": inverter(Eday=10.0)}), line({"I1": inverter(Eday=12.5)})],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    assert (
        read_state(workdir / "state.json")["inverters"]["stats"]["Eday"] == 12.5
    )


def test_the_power_of_an_optimizer_is_voltage_times_current(
    workdir, monkeypatch
):
    run_se2state(
        monkeypatch,
        [line(optimizers={"O1": optimizer(Vmod=30.0, Imod=2.5)})],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    assert read_state(workdir / "state.json")["optimizers"]["O1"]["Pdc"] == 75.0


def test_the_optimizer_temperature_is_averaged(workdir, monkeypatch):
    run_se2state(
        monkeypatch,
        [
            line(
                optimizers={
                    "O1": optimizer(Temp=30.0),
                    "O2": optimizer(Temp=50.0),
                }
            )
        ],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    stats = read_state(workdir / "state.json")["optimizers"]["stats"]
    assert stats["Temp"] == pytest.approx(40.0)


def test_without_devices_the_averages_are_zero_and_not_an_error(
    workdir, monkeypatch
):
    run_se2state(monkeypatch, [line()], "-i", "I1", "-o", "state.json")

    state = read_state(workdir / "state.json")
    assert state["inverters"]["stats"]["Temp"] == 0
    assert state["optimizers"]["stats"]["Temp"] == 0


# --- events ------------------------------------------------------------------


def test_an_event_zeroes_the_current_values_of_the_devices(
    workdir, monkeypatch
):
    run_se2state(
        monkeypatch,
        [
            line({"I1": inverter()}, {"O1": optimizer()}),
            line(events={"I1": {"Type": 1}}),
        ],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    state = read_state(workdir / "state.json")
    assert state["inverters"]["I1"]["Eac"] == 0.0
    assert state["inverters"]["I1"]["Pac"] == 0.0
    assert state["inverters"]["I1"]["Etot"] == 1000.0
    for key in ("Vmod", "Vopt", "Imod"):
        assert state["optimizers"]["O1"][key] == 0.0
    assert state["optimizers"]["O1"]["Temp"] == 40.0


def test_without_an_event_the_values_are_kept(workdir, monkeypatch):
    run_se2state(
        monkeypatch, [line({"I1": inverter()})], "-i", "I1", "-o", "state.json"
    )

    assert read_state(workdir / "state.json")["inverters"]["I1"]["Pac"] == 100.0


# --- input -------------------------------------------------------------------


def test_invalid_json_is_an_error(workdir, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "-i", "I1", "-o", "state.json"]
    )
    monkeypatch.setattr(sys, "stdin", Input(["not json\n"]))

    with pytest.raises(ValueError):
        runpy.run_path(str(SCRIPT), run_name="__main__")


def test_waits_for_data_instead_of_spinning(workdir, monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    run_se2state(
        monkeypatch,
        ["", "", line({"I1": inverter()})],
        "-i",
        "I1",
        "-o",
        "state.json",
    )

    assert len(sleeps) >= 3
    assert all(delay > 0 for delay in sleeps)
