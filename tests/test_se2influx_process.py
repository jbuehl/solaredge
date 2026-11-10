import importlib.util
from pathlib import Path
import shlex
import sys
import types

import pytest

pytest.importorskip("dateutil", reason="se2influx needs python-dateutil")

UTILITIES = Path(__file__).resolve().parent.parent / "utilities"
SCRIPT = UTILITIES / "se2influx.py"
WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "se2influx"


class FakeInfluxClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def influxdb(monkeypatch):
    module = types.ModuleType("influxdb")
    module.InfluxDBClient = FakeInfluxClient
    monkeypatch.setitem(sys.modules, "influxdb", module)
    return module


@pytest.fixture
def se(influxdb):
    spec = importlib.util.spec_from_file_location("se2influx_process", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- reader ------------------------------------------------------------------


# --- run ---------------------------------------------------------------------


# --- parse_args --------------------------------------------------------------


@pytest.fixture
def parse(se, monkeypatch):
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["se2influx.py", *args])
        return se.parse_args()

    return run


def test_the_defaults(parse):
    args = parse()

    assert args.host == "localhost"
    assert args.port == 8086
    assert args.username == "root"
    assert args.password == "root"
    assert args.database == "semonitor"
    assert args.ssl is False
    assert args.verify_ssl is False
    assert args.timeout is None
    assert args.retries == 3
    assert args.use_udp is False
    assert args.udp_port == 4444
    assert args.queue_size == 10000
    assert args.log_path is None
    assert args.max_log_size == 1024000
    assert args.local_tz is None
    assert args.stat_timer_secs is None
    assert args.debug is False


def test_every_option_can_be_given(parse):
    args = parse(
        "--host", "influx.lan",
        "--port", "9999",
        "--username", "solar",
        "--password", "secret",
        "--database", "db",
        "--ssl",
        "--verify_ssl",
        "--timeout", "7",
        "--retries", "5",
        "--use_udp",
        "--udp_port", "5555",
        "--queue_size", "50",
        "--log_path", "/var/log/se.log",
        "--max_log_size", "2048",
        "--local_tz", "Europe/Amsterdam",
        "--stat_timer_secs", "300",
        "--debug",
    )  # fmt: skip

    assert (args.host, args.username, args.password, args.database) == (
        "influx.lan",
        "solar",
        "secret",
        "db",
    )
    assert (args.ssl, args.verify_ssl, args.use_udp, args.debug) == (True,) * 4
    assert (args.timeout, args.stat_timer_secs) == (7, 300)
    assert (args.log_path, args.local_tz) == (
        "/var/log/se.log",
        "Europe/Amsterdam",
    )


# queue.Queue(maxsize="50") and the size comparison of the log need numbers
@pytest.mark.xfail(strict=True, reason="Issue #27")
@pytest.mark.parametrize(
    ("option", "attribute", "value"),
    [
        ("--port", "port", 9999),
        ("--retries", "retries", 5),
        ("--udp_port", "udp_port", 5555),
        ("--queue_size", "queue_size", 50),
        ("--max_log_size", "max_log_size", 2048),
    ],
)
def test_numeric_options_are_numbers(parse, option, attribute, value):
    assert getattr(parse(option, str(value)), attribute) == value


@pytest.mark.parametrize("option", ["--timeout", "--stat_timer_secs"])
def test_options_that_must_be_whole_numbers_refuse_text(parse, option, capsys):
    with pytest.raises(SystemExit) as exit_:
        parse(option, "soon")

    assert exit_.value.code == 2


def test_unknown_options_are_refused(parse):
    with pytest.raises(SystemExit) as exit_:
        parse("--no-such-option")

    assert exit_.value.code == 2


def test_help_lists_the_defaults(parse, capsys):
    with pytest.raises(SystemExit) as exit_:
        parse("--help")

    assert exit_.value.code == 0
    assert "8086" in capsys.readouterr().out


def test_the_options_of_the_wrapper_script_are_all_accepted(parse):
    text = WRAPPER.read_text()
    command = text[text.index("se2influx.py") + len("se2influx.py") :]
    command = command.split("\n\n")[0].replace("\\\n", " ").splitlines()[0]
    tokens = [
        "x" if token.startswith("$") else token
        for token in shlex.split(command)
    ]

    assert tokens
    parse(*tokens)


# --- main program ------------------------------------------------------------
