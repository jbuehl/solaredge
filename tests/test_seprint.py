import io
import json
from pathlib import Path
import runpy
import sys

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "utilities" / "seprint.py"


def run_seprint(monkeypatch, *args, stdin=""):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 1
    except KeyError, OSError, ValueError:
        # A traceback is a failure, it ends the script with an exit code of 1.
        return 1
    return 0


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


def inverter(time="12:00:00", eday=1234.5, pac=250.25, vac=240.5):
    return {
        "Date": "2016-01-01",
        "Time": time,
        "Eday": eday,
        "Pac": pac,
        "Vac": vac,
    }


def optimizer(time="12:00:00", eday=12.5):
    return {"Date": "2016-01-01", "Time": time, "Eday": eday}


def event(time="12:00:00"):
    return {"Date": "2016-01-01", "Time": time, "Type": 1}


# --- what is printed ---------------------------------------------------------


def test_an_inverter_is_printed_with_energy_power_and_voltage(
    monkeypatch, capsys
):
    assert run_seprint(monkeypatch, stdin=line({"7F104920": inverter()})) == 0

    assert capsys.readouterr().out.splitlines() == [
        "Inverters",
        "  2016-01-01 12:00:00 7F104920 Eday:  1234.50 Pac: 250.25 Vac:240.50",
    ]


def test_an_optimizer_is_printed_with_its_energy(monkeypatch, capsys):
    run_seprint(monkeypatch, stdin=line(optimizers={"8000AB": optimizer()}))

    assert capsys.readouterr().out.splitlines() == [
        "Optimizers",
        "  2016-01-01 12:00:00 8000AB Eday:  12.50",
    ]


def test_an_event_is_printed_with_its_time(monkeypatch, capsys):
    run_seprint(monkeypatch, stdin=line(events={"7F104920": event()}))

    assert capsys.readouterr().out.splitlines() == [
        "Events",
        "  2016-01-01 12:00:00 7F104920",
    ]


def test_the_sections_are_printed_in_the_order_inverters_optimizers_events(
    monkeypatch, capsys
):
    run_seprint(
        monkeypatch,
        stdin=line({"I1": inverter()}, {"O1": optimizer()}, {"E1": event()}),
    )

    headings = [
        row
        for row in capsys.readouterr().out.splitlines()
        if not row.startswith(" ")
    ]
    assert headings == ["Inverters", "Optimizers", "Events"]


def test_the_devices_of_a_section_are_sorted_by_name(monkeypatch, capsys):
    run_seprint(
        monkeypatch,
        stdin=line({"7F2": inverter(), "7F1": inverter(), "7F3": inverter()}),
    )

    names = [row.split()[2] for row in capsys.readouterr().out.splitlines()[1:]]
    assert names == ["7F1", "7F2", "7F3"]


def test_empty_sections_are_not_printed(monkeypatch, capsys):
    run_seprint(monkeypatch, stdin=line({"I1": inverter()}))

    out = capsys.readouterr().out
    assert "Optimizers" not in out
    assert "Events" not in out


def test_a_line_without_devices_prints_nothing(monkeypatch, capsys):
    run_seprint(monkeypatch, stdin=line())

    assert capsys.readouterr().out == ""


def test_every_line_of_the_input_is_printed(monkeypatch, capsys):
    run_seprint(
        monkeypatch,
        stdin=line({"I1": inverter("12:00:00")})
        + line({"I1": inverter("12:00:05")}),
    )

    rows = capsys.readouterr().out.splitlines()
    assert [row.split()[1] for row in rows if row.startswith("  ")] == [
        "12:00:00",
        "12:00:05",
    ]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {"eday": 0, "pac": 0, "vac": 0},
            "Eday:     0.00 Pac:   0.00 Vac:  0.00",
        ),
        (
            {"eday": -1.5, "pac": -2.5, "vac": -3.5},
            "Eday:    -1.50 Pac:  -2.50 Vac: -3.50",
        ),
        (
            {"eday": 123456.789, "pac": 1234.5678, "vac": 240.126},
            "Eday:123456.79 Pac:1234.57 Vac:240.13",
        ),
    ],
)
def test_the_numbers_are_fixed_width_with_two_decimals(
    monkeypatch, capsys, values, expected
):
    run_seprint(monkeypatch, stdin=line({"I1": inverter(**values)}))

    assert capsys.readouterr().out.splitlines()[1].endswith(expected)


# --- input -------------------------------------------------------------------


def test_empty_input_prints_nothing(monkeypatch, capsys):
    assert run_seprint(monkeypatch, stdin="") == 0

    assert capsys.readouterr().out == ""


@pytest.mark.xfail(strict=True, reason="Issue #45")
def test_a_file_that_does_not_exist_is_an_error_not_a_fallback_to_stdin(
    monkeypatch, capsys
):
    code = run_seprint(
        monkeypatch, "missing.json", stdin=line({"I1": inverter()})
    )

    assert code != 0
    assert "Inverters" not in capsys.readouterr().out


def test_invalid_json_is_an_error(monkeypatch):
    assert run_seprint(monkeypatch, stdin="not json\n") != 0


def test_a_device_without_the_expected_fields_is_an_error(monkeypatch):
    broken = {"Date": "2016-01-01", "Time": "12:00:00"}

    assert run_seprint(monkeypatch, stdin=line({"I1": broken})) != 0
