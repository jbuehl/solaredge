import se.msg

LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
SMALLEST_SAMPLE = "Geoff99.190801.1135.test"


# Without git-lfs the golden files are pointers, so everything would fail
# in confusing ways.
def test_golden_data_is_checked_out(golden_dir, sample):
    paths = [path for path in golden_dir.rglob(f"{sample}.*") if path.is_file()]

    assert {path.suffix for path in paths} >= {".json", ".rec"}
    for path in paths:
        assert path.stat().st_size > 0, path
        assert not path.read_bytes().startswith(LFS_POINTER), path


def test_message_roundtrip():
    msg = se.msg.formatMsg(1234, 0xFFFFFFFE, 0x7F104920, 0x0501, b"\x01\x02")

    assert se.msg.parseMsg(bytes(msg)) == (
        1234,
        0xFFFFFFFE,
        0x7F104920,
        0x0501,
        b"\x01\x02",
    )


def test_run_reports_the_exit_code(run_semonitor):
    result = run_semonitor("-h")

    assert result.returncode == 0
    assert result.stdout.startswith(b"usage: ")

    result = run_semonitor("--no-such-option")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_runs_do_not_influence_each_other(run_semonitor, golden_dir):
    rec = golden_dir / "rec" / f"{SMALLEST_SAMPLE}.rec"

    first = run_semonitor("-x", rec)
    second = run_semonitor("-x", rec)

    assert first.returncode == 0
    assert first.stdout
    assert second == first
