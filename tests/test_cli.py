import json
import runpy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEVICE = {
    "Date": "2020-01-01",
    "Time": "10:00:00",
    "Eday": 1.0,
    "Pac": 2.0,
    "Vac": 3.0,
}
DATA = {"inverters": {"I1": DEVICE}, "optimizers": {}, "events": {}}


def load(monkeypatch, directory, name):
    # The commands are not part of a package yet, so load one as a script is,
    # but without running it as __main__.
    path = ROOT / directory / f"{name}.py"
    monkeypatch.syspath_prepend(str(path.parent))
    monkeypatch.delitem(sys.modules, "common", raising=False)
    return types.SimpleNamespace(**runpy.run_path(str(path), run_name=name))


@pytest.fixture
def seprint(monkeypatch):
    return load(monkeypatch, "utilities", "seprint")


@pytest.fixture
def se2csv(monkeypatch):
    return load(monkeypatch, "conversion", "se2csv")


# The entry points call main() without arguments, so main() has to take the
# arguments of the process then. Giving it arguments has to work as well, and
# has to ignore those of the process.
def test_seprint_main_reads_the_file_it_is_given(seprint, tmp_path, capsys):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")

    seprint.main([str(path)])

    assert capsys.readouterr().out.splitlines()[0] == "Inverters"


def test_seprint_main_defaults_to_the_arguments_of_the_process(
    seprint, tmp_path, capsys, monkeypatch
):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")
    monkeypatch.setattr("sys.argv", ["seprint", str(path)])

    seprint.main()

    assert capsys.readouterr().out.splitlines()[0] == "Inverters"


def test_se2csv_main_uses_the_arguments_it_is_given(
    se2csv, tmp_path, monkeypatch
):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")
    monkeypatch.setattr("sys.argv", ["se2csv", "--no-such-option"])

    se2csv.main(["-p", str(tmp_path / "out"), str(path)])

    assert (tmp_path / "out.inverters.csv").exists()
