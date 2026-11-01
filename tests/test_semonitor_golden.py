from pathlib import Path
import re

import pytest


def test_output_matches_the_golden_data(run_semonitor, golden, sample):
    result = run_semonitor(
        "-v",
        "-x",
        "-r",
        "out.rec",
        "-o",
        "out.json",
        golden("rec", sample),
    )

    assert result.returncode == 0
    assert Path("out.json").read_bytes() == golden("json", sample).read_bytes()
    assert Path("out.rec").read_bytes() == golden("rec", sample).read_bytes()


def test_output_defaults_to_stdout(run_semonitor, golden, sample):
    result = run_semonitor("-x", golden("rec", sample))

    assert result.returncode == 0
    assert result.stdout == golden("json", sample).read_bytes()


def test_output_is_not_overwritten_without_append(
    run_semonitor, golden, sample
):
    args = ("-x", "-r", "out.rec", "-o", "out.json", golden("rec", sample))

    assert run_semonitor(*args).returncode == 0
    assert run_semonitor(*args).returncode == 0

    for name in ("out.json", "out.1.json"):
        assert Path(name).read_bytes() == golden("json", sample).read_bytes()
    for name in ("out.rec", "out.1.rec"):
        assert Path(name).read_bytes() == golden("rec", sample).read_bytes()
    assert not Path("out.2.json").exists()
    assert not Path("out.2.rec").exists()


def test_date_in_the_output_names_is_never_overwritten(
    run_semonitor, golden, sample
):
    args = (
        "-x",
        "-r",
        "out.__date__.rec",
        "-o",
        "out.__date__.json",
        golden("rec", sample),
    )

    assert run_semonitor(*args).returncode == 0
    assert run_semonitor(*args).returncode == 0

    for kind, suffix in (("json", "json"), ("rec", "rec")):
        names = sorted(path.name for path in Path().glob(f"out.*.{suffix}"))
        assert len(names) == 2
        # out.YYYYMMDD.ext and, as that exists, out.YYYYMMDD.1.ext
        (first, second) = sorted(names, key=len)
        assert re.fullmatch(rf"out\.\d{{8}}\.{suffix}", first)
        assert second == first.replace(f".{suffix}", f".1.{suffix}")
        for name in names:
            assert Path(name).read_bytes() == golden(kind, sample).read_bytes()
    assert not Path("out.__date__.json").exists()
    assert not Path("out.__date__.rec").exists()


def test_datetime_in_the_output_names_is_replaced(
    run_semonitor, golden, sample
):
    result = run_semonitor(
        "-x",
        "-r",
        "out.__datetime__.rec",
        "-o",
        "out.__datetime__.json",
        golden("rec", sample),
    )

    assert result.returncode == 0
    for kind, suffix in (("json", "json"), ("rec", "rec")):
        (path,) = Path().glob(f"out.*.{suffix}")
        assert re.fullmatch(rf"out\.\d{{14}}\.{suffix}", path.name)
        assert path.read_bytes() == golden(kind, sample).read_bytes()


def test_append_adds_to_the_existing_output(run_semonitor, golden, sample):
    args = ("-x", "-r", "out.rec", "-o", "out.json", golden("rec", sample))

    assert run_semonitor(*args).returncode == 0
    assert run_semonitor("-a", *args).returncode == 0

    assert (
        Path("out.json").read_bytes() == golden("json", sample).read_bytes() * 2
    )
    assert (
        Path("out.rec").read_bytes() == golden("rec", sample).read_bytes() * 2
    )


def test_unknown_option_is_a_usage_error(run_semonitor):
    result = run_semonitor("--no-such-option")

    assert result.returncode == 2
    assert result.stdout.startswith(b"")
    assert "unrecognized arguments" in result.stderr


@pytest.mark.parametrize("option", ["-t", "-b", "-c", "-s", "-o", "-r", "-d"])
def test_option_without_a_value_is_a_usage_error(run_semonitor, option):
    result = run_semonitor(option)

    assert result.returncode == 2
    assert "expected one argument" in result.stderr
