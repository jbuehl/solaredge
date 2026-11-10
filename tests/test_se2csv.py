import io
import json
from pathlib import Path
import runpy
import sys

import pytest

CONVERSION = Path(__file__).resolve().parent.parent / "conversion"
SCRIPT = CONVERSION / "se2csv.py"


def run_se2csv(monkeypatch, *args, stdin=""):
    monkeypatch.syspath_prepend(str(CONVERSION))
    monkeypatch.delitem(sys.modules, "common", raising=False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = 0
    opened = []
    real_open = open

    def tracking_open(*open_args, **open_kwargs):
        handle = real_open(*open_args, **open_kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else 1
    finally:
        # What happens to the files that are open when the interpreter exits.
        for handle in opened:
            handle.close()
    return code


def inverter(ident, **extra):
    return {
        "Date": "2016-01-01",
        "ID": ident,
        "Pac": 1.5,
        "Time": "12:00:00",
        **extra,
    }


def line(**sections):
    data = {"events": {}, "inverters": {}, "optimizers": {}}
    data.update(sections)
    return json.dumps(data) + "\n"


def normalized(text):
    return ["".join(row.split()) for row in text.splitlines()]


# --- command line ------------------------------------------------------------


def test_prefix_is_required(monkeypatch, capsys):
    assert run_se2csv(monkeypatch) == 2
    assert "-p" in capsys.readouterr().err


def test_help_describes_the_tool(monkeypatch, capsys):
    assert run_se2csv(monkeypatch, "-h") == 0

    out = capsys.readouterr().out
    for option in ("-a", "-d", "-t", "-p"):
        assert option in out


@pytest.mark.parametrize("option", ["-i", "-o", "-e"])
def test_deprecated_options_are_refused(monkeypatch, capsys, option):
    assert run_se2csv(monkeypatch, "-p", "out", option, "x") == 2
    assert "deprecated" in capsys.readouterr().err.lower()


# --- output ------------------------------------------------------------------


def test_each_device_type_gets_its_own_file(workdir, monkeypatch):
    stdin = line(
        inverters={"I1": inverter("I1")},
        optimizers={
            "O1": {"Date": "2016-01-01", "Time": "12:00:00", "ID": "O1"}
        },
    )

    assert run_se2csv(monkeypatch, "-p", "out", stdin=stdin) == 0

    assert sorted(path.name for path in workdir.iterdir()) == [
        "out.inverters.csv",
        "out.optimizers.csv",
    ]


def test_the_identifier_is_the_first_column_and_the_rest_is_sorted(
    workdir, monkeypatch
):
    stdin = line(inverters={"I1": inverter("I1")})

    run_se2csv(monkeypatch, "-p", "out", "-t", stdin=stdin)

    assert (workdir / "out.inverters.csv").read_text().splitlines() == [
        "__Identifier__,Date,ID,Pac,Time",
        "I1,2016-01-01,I1,1.5,12:00:00",
    ]


def test_headers_are_only_written_on_request(workdir, monkeypatch):
    stdin = line(inverters={"I1": inverter("I1")})

    run_se2csv(monkeypatch, "-p", "out", stdin=stdin)

    assert (workdir / "out.inverters.csv").read_text().splitlines() == [
        "I1,2016-01-01,I1,1.5,12:00:00"
    ]


def test_a_row_is_written_for_every_device_of_every_line(workdir, monkeypatch):
    stdin = line(inverters={"I1": inverter("I1"), "I2": inverter("I2")})
    stdin += line(inverters={"I1": inverter("I1", Pac=2.5)})

    run_se2csv(monkeypatch, "-p", "out", stdin=stdin)

    rows = (workdir / "out.inverters.csv").read_text().splitlines()
    assert [row.split(",")[0] for row in rows] == ["I1", "I2", "I1"]
    assert rows[2].split(",")[3] == "2.5"


@pytest.mark.xfail(strict=True, reason="Issue #29")
def test_the_delimiter_can_be_changed(workdir, monkeypatch):
    stdin = line(inverters={"I1": inverter("I1")})

    run_se2csv(monkeypatch, "-p", "out", "-d", ";", "-t", stdin=stdin)

    assert (workdir / "out.inverters.csv").read_text().splitlines()[0] == (
        "__Identifier__;Date;ID;Pac;Time"
    )


def test_the_prefix_may_contain_a_directory(workdir, monkeypatch):
    (workdir / "sub").mkdir()

    run_se2csv(
        monkeypatch,
        "-p",
        workdir / "sub" / "site",
        stdin=line(inverters={"I1": inverter("I1")}),
    )

    assert (workdir / "sub" / "site.inverters.csv").is_file()


def test_the_file_is_overwritten_without_append(workdir, monkeypatch):
    (workdir / "out.inverters.csv").write_text("old\n")

    run_se2csv(
        monkeypatch, "-p", "out", stdin=line(inverters={"I1": inverter("I1")})
    )

    assert "old" not in (workdir / "out.inverters.csv").read_text()


def test_the_file_is_extended_with_append(workdir, monkeypatch):
    (workdir / "out.inverters.csv").write_text("old\n")

    run_se2csv(
        monkeypatch,
        "-p",
        "out",
        "-a",
        stdin=line(inverters={"I1": inverter("I1")}),
    )

    assert (workdir / "out.inverters.csv").read_text().splitlines() == [
        "old",
        "I1,2016-01-01,I1,1.5,12:00:00",
    ]


def test_no_input_creates_no_files(workdir, monkeypatch):
    assert run_se2csv(monkeypatch, "-p", "out", stdin="") == 0

    assert list(workdir.iterdir()) == []


def test_lines_without_devices_create_no_files(workdir, monkeypatch):
    assert run_se2csv(monkeypatch, "-p", "out", stdin=line() * 3) == 0

    assert list(workdir.iterdir()) == []


def test_a_missing_input_file_is_an_error(monkeypatch, capsys):
    assert run_se2csv(monkeypatch, "-p", "out", "missing.json") == 2
    assert "missing.json" in capsys.readouterr().err


def test_invalid_json_is_an_error_not_a_silent_skip(workdir, monkeypatch):
    with pytest.raises(json.JSONDecodeError):
        run_se2csv(monkeypatch, "-p", "out", stdin="not json\n")


def test_device_names_with_spaces_are_made_safe_for_file_names(
    workdir, monkeypatch
):
    stdin = line(
        **{"Unknown device": {"I 1": inverter("I 1")}},
    )

    run_se2csv(monkeypatch, "-p", "out", stdin=stdin)

    assert (workdir / "out.Unknown_device.csv").is_file()


def test_nan_and_infinity_from_semonitor_are_written_as_floats(
    workdir, monkeypatch
):
    # semonitor writes the values that are not populated as NaN in its json
    row = inverter("I1", Temp=float("nan"), Vdc=float("-inf"))

    run_se2csv(
        monkeypatch, "-p", "out", "-t", stdin=line(inverters={"I1": row})
    )

    header, data = (workdir / "out.inverters.csv").read_text().splitlines()
    fields = dict(zip(header.split(","), data.split(","), strict=True))
    assert fields["Temp"].lower() == "nan"
    assert fields["Vdc"].lower() == "-inf"
