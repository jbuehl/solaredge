from pathlib import Path

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


def test_output_is_overwritten_without_append(run_semonitor, golden, sample):
    args = ("-x", "-r", "out.rec", "-o", "out.json", golden("rec", sample))

    assert run_semonitor(*args).returncode == 0
    assert run_semonitor(*args).returncode == 0

    assert Path("out.json").read_bytes() == golden("json", sample).read_bytes()
    assert Path("out.rec").read_bytes() == golden("rec", sample).read_bytes()


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
