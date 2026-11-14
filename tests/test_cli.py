import json

from se import se2csv, seprint

DEVICE = {
    "Date": "2020-01-01",
    "Time": "10:00:00",
    "Eday": 1.0,
    "Pac": 2.0,
    "Vac": 3.0,
}
DATA = {"inverters": {"I1": DEVICE}, "optimizers": {}, "events": {}}


# The entry points call main() without arguments, so main() has to take the
# arguments of the process then. Giving it arguments has to work as well, and
# has to ignore those of the process.
def test_seprint_main_reads_the_file_it_is_given(tmp_path, capsys):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")

    seprint.main([str(path)])

    assert capsys.readouterr().out.splitlines()[0] == "Inverters"


def test_seprint_main_defaults_to_the_arguments_of_the_process(
    tmp_path, capsys, monkeypatch
):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")
    monkeypatch.setattr("sys.argv", ["seprint", str(path)])

    seprint.main()

    assert capsys.readouterr().out.splitlines()[0] == "Inverters"


def test_se2csv_main_uses_the_arguments_it_is_given(tmp_path, monkeypatch):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(DATA) + "\n")
    monkeypatch.setattr("sys.argv", ["se2csv", "--no-such-option"])

    se2csv.main(["-p", str(tmp_path / "out"), str(path)])

    assert (tmp_path / "out.inverters.csv").exists()
