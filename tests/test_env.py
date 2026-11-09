import logging
import logging.handlers
import re
import sys

import pytest
import serial.tools.list_ports
import serial.tools.list_ports_common

import se.env
import se.logutils

FILE_TIMESTAMP = r"[A-Z][a-z]{2} \d\d \d\d:\d\d:\d\d"
NO_SLAVES = "At least one slave address must be specified for master mode"
ONE_SLAVE = "Exactly one slave address must be specified for command mode"
RS485_ONLY = "Master mode only allowed with RS485 serial device"
NO_SERIAL_TYPE = "Input device type 2 or 4 must be specified for serial device"
NOT_SERIAL = " is not a valid serial device\n"
ONLY_SERIAL = "Input device types 2 and 4 are only valid for a serial device"


def verbose_flags(count):
    return ["-" + ("v" * count)] if count else []


def run_mode(**fields):
    return se.env.RunMode(
        **{
            "serialDevice": False,
            "serialType": None,
            "passiveMode": True,
            "masterMode": False,
            "following": False,
            **fields,
        }
    )


@pytest.fixture(autouse=True)
def no_serial_ports(monkeypatch):
    monkeypatch.setattr(serial.tools.list_ports, "comports", list)


# The name of a serial port that exists, for both kinds of port list.
# pyserial gives ListPortInfo objects, older versions gave plain tuples.
@pytest.fixture(
    params=["/dev/ttyUSB0", "/dev/ttyS9"], ids=["ListPortInfo", "tuple"]
)
def serial_port(request, monkeypatch):
    ports = [
        serial.tools.list_ports_common.ListPortInfo(
            "/dev/ttyUSB0", skip_link_detection=True
        ),
        ("/dev/ttyS9", "description", "hardware id"),
    ]
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: ports)
    return request.param


# Return a function that runs se.env.getArgs() with the given arguments.
# getArgs() adds a handler to the root logger and sets its level. Undo that,
# but only for the handlers added here: the root logger also holds the
# handlers of pytest itself.
@pytest.fixture
def get_args(monkeypatch):
    root = logging.getLogger()
    level = root.level
    added = []

    def run(*argv):
        before = root.handlers[:]
        monkeypatch.setattr(sys, "argv", ["semonitor.py", *map(str, argv)])
        try:
            return se.env.getArgs()
        finally:
            added.extend(h for h in root.handlers if h not in before)

    yield run

    for handler in added:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)


@pytest.fixture
def usage_error(get_args, capsys):

    def run(*argv):
        with pytest.raises(SystemExit) as exit_:
            get_args(*argv)
        captured = capsys.readouterr()
        assert exit_.value.code == 2
        assert captured.out.startswith("usage: ")
        return captured.err

    return run


# the defaults


def test_defaults_without_arguments(get_args):
    args, mode = get_args()

    assert vars(args) == {
        "append": False,
        "baudrate": 115200,
        "commands": [],
        "datasource": "stdin",
        "follow": False,
        "logfile": "stderr",
        "master": False,
        "outfile": "stdout",
        "record": None,
        "slaves": [],
        "type": None,
        "updatefile": None,
        "verbose": 0,
        "xerror": False,
    }
    assert mode == run_mode()


def test_plain_options_are_stored(get_args):
    args, mode = get_args(
        "-a", "-b", 9600, "-f", "-o", "out.json", "-r", "rec.bin", "-x"
    )

    assert args.append
    assert args.baudrate == 9600
    assert args.follow
    assert args.outfile == "out.json"
    assert args.record == "rec.bin"
    assert args.xerror
    assert mode == run_mode(following=True)


def test_update_file_is_opened_for_writing(get_args, workdir):
    args, _ = get_args("-u", "firmware.bin")

    with args.updatefile as update:
        assert update.name == "firmware.bin"
        assert update.writable()
    assert (workdir / "firmware.bin").exists()


def test_run_mode_has_a_name_for_each_field():
    assert se.env.RunMode._fields == (
        "serialDevice",
        "serialType",
        "passiveMode",
        "masterMode",
        "following",
    )


# the argument parser


def test_parser_error_prints_the_usage_and_exits_with_2(capsys):
    parser = se.env.SeArgumentParser(prog="prog")

    with pytest.raises(SystemExit) as exit_:
        parser.error("something is wrong")

    captured = capsys.readouterr()
    assert exit_.value.code == 2
    assert captured.out.startswith("usage: prog")
    assert captured.err == "something is wrong\n"


# the argument validators


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("0", [["0"]], id="single"),
        pytest.param("0a", [["0a"]], id="hex"),
        pytest.param("FfA0", [["FfA0"]], id="upper-case"),
        pytest.param("0a,b1", [["0a", "b1"]], id="byte-argument"),
        pytest.param(
            "0a,b1,H22,l3F", [["0a", "b1", "H22", "l3F"]], id="all-widths"
        ),
        pytest.param("0a/0b", [["0a"], ["0b"]], id="two-commands"),
        pytest.param(
            "0a,l10/0b/ff,B1,h2",
            [["0a", "l10"], ["0b"], ["ff", "B1", "h2"]],
            id="three-commands",
        ),
    ],
)
def test_commands_are_split_per_command_and_argument(get_args, value, expected):
    args, _ = get_args("-c", value, "-s", "1")

    assert args.commands == expected


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        pytest.param("", "", id="empty"),
        pytest.param("xyz", "xyz", id="not-hex"),
        pytest.param("0a,", "0a,", id="trailing-comma"),
        pytest.param("0a,10", "0a,10", id="argument-without-width"),
        pytest.param("0a,x10", "0a,x10", id="unknown-width"),
        pytest.param("0a,b", "0a,b", id="width-without-value"),
        pytest.param("0a/", "", id="trailing-slash"),
        pytest.param("0a//0b", "", id="empty-command"),
        pytest.param("0a/zz", "zz", id="second-command-bad"),
        pytest.param("0a b", "0a b", id="space"),
    ],
)
def test_invalid_commands_are_rejected(usage_error, value, bad):
    message = usage_error("-c", value, "-s", "1")

    assert message == f"argument -c: Invalid command: {bad}\n"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("1", ["1"], id="single"),
        pytest.param("7f104920", ["7f104920"], id="serial-number"),
        pytest.param("7F104920,0a", ["7F104920", "0a"], id="two"),
        pytest.param("1,2,3", ["1", "2", "3"], id="three"),
    ],
)
def test_slaves_are_a_list_of_ids(get_args, value, expected):
    args, _ = get_args("-s", value)

    assert args.slaves == expected


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        pytest.param("", "", id="empty"),
        pytest.param("xyz", "xyz", id="not-hex"),
        pytest.param("1,,2", "", id="empty-slave"),
        pytest.param("1,", "", id="trailing-comma"),
        pytest.param("1,0x2", "0x2", id="prefix"),
        pytest.param("1,g", "g", id="second-bad"),
    ],
)
def test_invalid_slaves_are_rejected(usage_error, value, bad):
    message = usage_error("-s", value)

    assert message == f"argument -s: Invalid slave ID: {bad}\n"


@pytest.mark.parametrize("value", ["2", "4"])
def test_type_accepts_rs232_and_rs485(get_args, serial_port, value):
    args, _ = get_args("-t", value, serial_port)

    assert args.type == value


@pytest.mark.parametrize("value", ["", "1", "3", "n", "N", "x", "24"])
def test_type_rejects_other_values(usage_error, value):
    message = usage_error("-t", value)

    assert message.startswith("argument -t: invalid choice: ")


@pytest.mark.parametrize("option", ["-p", "-n"])
def test_options_of_other_versions_are_gone(usage_error, option):
    message = usage_error(option, "80")

    assert message == f"unrecognized arguments: {option}\n"


def test_baudrate_must_be_a_number(usage_error):
    message = usage_error("-b", "fast")

    assert "argument -b: invalid int value: 'fast'" in message


def test_unknown_option_is_a_usage_error(usage_error):
    message = usage_error("--no-such-option")

    assert message == "unrecognized arguments: --no-such-option\n"


def test_only_one_datasource_is_accepted(usage_error):
    message = usage_error("one.rec", "two.rec")

    assert message == "unrecognized arguments: two.rec\n"


# logging


def test_logs_to_stderr_by_default(get_args, capsys):
    get_args("-v")

    captured = capsys.readouterr()
    assert "xerror: False\n" in captured.err
    assert not captured.out


def test_logs_to_stderr_when_asked(get_args, capsys):
    get_args("-v", "-d", "stderr")

    captured = capsys.readouterr()
    assert "xerror: False\n" in captured.err
    assert not captured.out


def test_logs_to_stdout_when_asked(get_args, capsys):
    get_args("-v", "-d", "stdout")

    captured = capsys.readouterr()
    assert "xerror: False\n" in captured.out
    assert not captured.err


def test_logs_to_syslog_when_asked(get_args, monkeypatch):
    created = []

    def fake_syslog_handler(*args, **kwargs):
        handler = logging.NullHandler()
        created.append((args, kwargs, handler))
        return handler

    monkeypatch.setattr(logging.handlers, "SysLogHandler", fake_syslog_handler)

    get_args("-d", "syslog")

    ((args, kwargs, handler),) = created
    assert (args, kwargs) == ((), {"address": "/dev/log"})
    assert handler in logging.getLogger().handlers
    record = logging.makeLogRecord({"msg": "hello"})
    assert handler.format(record) == "hello"


def test_logs_to_a_file_with_a_timestamp(get_args, workdir):
    get_args("-v", "-d", "semonitor.log")

    lines = (workdir / "semonitor.log").read_text().splitlines()
    assert lines
    assert all(re.fullmatch(FILE_TIMESTAMP + " .+", line) for line in lines)
    assert any(line.endswith(" xerror: False") for line in lines)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        pytest.param([], "", id="truncates"),
        pytest.param(["-a"], "old\n", id="appends"),
    ],
)
def test_log_file_is_truncated_unless_appending(
    get_args, workdir, capsys, options, expected
):
    logfile = workdir / "semonitor.log"
    logfile.write_text("old\n")

    get_args(*options, "-d", "semonitor.log")

    assert logfile.read_text() == expected
    assert not capsys.readouterr().err


def test_log_file_is_appended_to_after_the_old_content(get_args, workdir):
    logfile = workdir / "semonitor.log"
    logfile.write_text("old\n")

    get_args("-v", "-a", "-d", "semonitor.log")

    lines = logfile.read_text().splitlines()
    assert lines[0] == "old"
    assert len(lines) > 1


@pytest.mark.xfail(strict=True, reason="Issue #40")
def test_empty_log_destination_is_a_usage_error(usage_error):
    message = usage_error("-d", "")

    assert message


@pytest.mark.parametrize(
    ("count", "level"),
    [
        pytest.param(0, logging.ERROR, id="none"),
        pytest.param(1, logging.INFO, id="v"),
        pytest.param(2, logging.DEBUG, id="vv"),
        pytest.param(3, se.logutils.LOG_LEVEL_DATA, id="vvv"),
        pytest.param(4, se.logutils.LOG_LEVEL_RAW, id="vvvv"),
        pytest.param(5, se.logutils.LOG_LEVEL_RAW, id="vvvvv"),
        pytest.param(9, se.logutils.LOG_LEVEL_RAW, id="vvvvvvvvv"),
    ],
)
def test_verbosity_sets_the_log_level(get_args, count, level):
    args, _ = get_args(*verbose_flags(count))

    assert args.verbose == count
    assert logging.getLogger().level == level


def test_verbosity_can_be_split_over_options(get_args):
    args, _ = get_args("-v", "-v", "-v")

    assert args.verbose == 3
    assert logging.getLogger().level == se.logutils.LOG_LEVEL_DATA


def test_log_levels_get_more_verbose_with_each_v(get_args):
    levels = []
    for count in range(5):
        get_args(*verbose_flags(count))
        levels.append(logging.getLogger().level)

    assert levels == sorted(levels, reverse=True)
    assert len(set(levels)) == len(levels)


def test_nothing_is_dumped_without_verbose(get_args, capsys):
    get_args("-c", "0a", "-s", "1")

    assert not capsys.readouterr().err


def test_verbose_dumps_the_default_arguments(get_args, capsys):
    get_args("-v")

    assert capsys.readouterr().err == (
        "append: False\n"
        "baudrate: 115200\n"
        "commands: \n"
        "datasource: stdin\n"
        "follow: False\n"
        "logfile: stderr\n"
        "master: False\n"
        "outfile: stdout\n"
        "record: None\n"
        "slaves: \n"
        "type: None\n"
        "updatefile: None\n"
        "verbose: 1\n"
        "xerror: False\n"
    )


def test_verbose_dumps_all_arguments_sorted_by_name(get_args, capsys):
    get_args(
        *("-a", "-b", 9600, "-c", "0a,l10/0b", "-f", "-o", "out.json"),
        *("-r", "rec.bin", "-s", "7f", "-v", "-x", "-"),
    )

    assert capsys.readouterr().err == (
        "append: True\n"
        "baudrate: 9600\n"
        "commands: 0a,l10 0b\n"
        "datasource: stdin\n"
        "follow: True\n"
        "logfile: stderr\n"
        "master: False\n"
        "outfile: out.json\n"
        "record: rec.bin\n"
        "slaves: 7f\n"
        "type: None\n"
        "updatefile: None\n"
        "verbose: 1\n"
        "xerror: True\n"
    )


def test_verbose_dumps_multiple_slaves(get_args, capsys):
    get_args("-v", "-s", "7f,80,81")

    lines = capsys.readouterr().err.splitlines()
    assert "slaves: 7f,80,81" in lines


# the data source and the mode


NON_SERIAL_MODES = [
    pytest.param([], "stdin", run_mode(), id="stdin-by-default"),
    pytest.param(["-"], "stdin", run_mode(), id="stdin-dash"),
    pytest.param(["stdin"], "stdin", run_mode(), id="stdin-name"),
    pytest.param(["capture.rec"], "capture.rec", run_mode(), id="file"),
    pytest.param(
        ["-f", "capture.rec"],
        "capture.rec",
        run_mode(following=True),
        id="file-following",
    ),
    pytest.param(
        ["-f"], "stdin", run_mode(following=True), id="stdin-following"
    ),
    pytest.param(
        ["-c", "0a", "-s", "7f104920"],
        "stdin",
        run_mode(passiveMode=False),
        id="command-on-stdin",
    ),
    pytest.param(
        ["-c", "0a/0b", "-s", "1", "capture.rec"],
        "capture.rec",
        run_mode(passiveMode=False),
        id="commands-on-a-file",
    ),
]


@pytest.mark.parametrize(("argv", "datasource", "expected"), NON_SERIAL_MODES)
def test_mode_without_a_serial_device(get_args, argv, datasource, expected):
    args, mode = get_args(*argv)

    assert args.datasource == datasource
    assert mode == expected


# A serial device is meant to be followed, see test_serial_device_is_followed.
# The RunMode is compared without that field here, so that these tests only
# check the rest. The same goes for -t 2 without master or commands, see
# test_rs232_mode_is_not_passive, which is left out of the table.
SERIAL_MODES = [
    pytest.param(
        ["-t", "4", "{port}"],
        run_mode(serialDevice=True, serialType="4"),
        id="rs485",
    ),
    pytest.param(
        ["-f", "-t", "4", "{port}"],
        run_mode(serialDevice=True, serialType="4"),
        id="rs485-follow-option",
    ),
    pytest.param(
        ["-m", "-t", "4", "-s", "1,2", "{port}"],
        run_mode(
            serialDevice=True,
            serialType="4",
            passiveMode=False,
            masterMode=True,
        ),
        id="rs485-master",
    ),
    pytest.param(
        ["-t", "4", "-c", "0a", "-s", "1", "{port}"],
        run_mode(serialDevice=True, serialType="4", passiveMode=False),
        id="rs485-command",
    ),
    pytest.param(
        ["-t", "2", "-c", "0a", "-s", "1", "{port}"],
        run_mode(serialDevice=True, serialType="2", passiveMode=False),
        id="rs232-command",
    ),
    pytest.param(
        ["-m", "-t", "4", "-s", "1", "-c", "0a", "{port}"],
        run_mode(
            serialDevice=True,
            serialType="4",
            passiveMode=False,
            masterMode=True,
        ),
        id="rs485-master-and-command",
    ),
]


@pytest.mark.parametrize(("argv", "expected"), SERIAL_MODES)
def test_mode_with_a_serial_device(get_args, serial_port, argv, expected):
    args, mode = get_args(*(a.format(port=serial_port) for a in argv))

    assert args.datasource == serial_port
    assert mode._replace(following=False) == expected


@pytest.mark.parametrize("serial_type", ["2", "4"])
def test_serial_device_with_its_type(get_args, serial_port, serial_type):
    _args, mode = get_args("-t", serial_type, serial_port)

    assert mode.serialDevice
    assert mode.serialType == serial_type
    assert not mode.masterMode


def test_serial_device_is_followed_with_the_follow_option(
    get_args, serial_port
):
    _args, mode = get_args("-f", "-t", "4", serial_port)

    assert mode.following


@pytest.mark.usefixtures("serial_port")
def test_unknown_device_is_not_a_serial_device(get_args):
    args, mode = get_args("/dev/ttyNOPE")

    assert args.datasource == "/dev/ttyNOPE"
    assert mode == run_mode()


@pytest.mark.usefixtures("serial_port")
def test_only_the_device_name_of_a_port_counts(get_args):
    args, mode = get_args("description")

    assert args.datasource == "description"
    assert mode == run_mode()


def test_a_port_that_is_not_listed_is_not_a_serial_device(usage_error):
    message = usage_error("-t", "4", "/dev/ttyUSB0")

    assert message == f"/dev/ttyUSB0{NOT_SERIAL}{ONLY_SERIAL}\n"


@pytest.mark.xfail(strict=True, reason="Issue #12")
def test_rs232_mode_is_not_passive(get_args, serial_port):
    _args, mode = get_args("-t", "2", serial_port)

    assert not mode.passiveMode


@pytest.mark.xfail(strict=True, reason="Issue #39")
@pytest.mark.parametrize("serial_type", ["2", "4"])
def test_serial_device_is_followed(get_args, serial_port, serial_type):
    _args, mode = get_args("-t", serial_type, serial_port)

    assert mode.following


# the usage errors


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(
            ["-t", "2"],
            f"stdin{NOT_SERIAL}{ONLY_SERIAL}",
            id="rs232-on-stdin",
        ),
        pytest.param(
            ["-t", "4"],
            f"stdin{NOT_SERIAL}{ONLY_SERIAL}",
            id="rs485-on-stdin",
        ),
        pytest.param(
            ["-t", "4", "-"],
            f"stdin{NOT_SERIAL}{ONLY_SERIAL}",
            id="rs485-on-stdin-dash",
        ),
        pytest.param(
            ["-t", "4", "capture.rec"],
            f"capture.rec{NOT_SERIAL}{ONLY_SERIAL}",
            id="rs485-on-a-file",
        ),
        pytest.param(
            ["-t", "2", "/dev/ttyNOPE"],
            f"/dev/ttyNOPE{NOT_SERIAL}{ONLY_SERIAL}",
            id="rs232-on-a-missing-device",
        ),
        pytest.param(
            ["-m", "-t", "4", "-s", "1"],
            f"stdin{NOT_SERIAL}{ONLY_SERIAL}",
            id="master-rs485-on-stdin",
        ),
        pytest.param(["-m"], RS485_ONLY, id="master-on-stdin"),
        pytest.param(["-m", "-s", "1", "-f"], RS485_ONLY, id="master-on-file"),
        pytest.param(["-c", "0a"], ONE_SLAVE, id="command-without-slave"),
        pytest.param(
            ["-c", "0a", "-s", "1,2"], ONE_SLAVE, id="command-with-two-slaves"
        ),
    ],
)
def test_invalid_combinations_are_usage_errors(usage_error, argv, message):
    assert usage_error(*argv) == f"{message}\n"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(["{port}"], NO_SERIAL_TYPE, id="no-type"),
        pytest.param(
            ["-m", "-t", "2", "-s", "1", "{port}"],
            RS485_ONLY,
            id="master-rs232",
        ),
        pytest.param(
            ["-m", "-s", "1", "{port}"], NO_SERIAL_TYPE, id="master-no-type"
        ),
        pytest.param(
            ["-m", "-t", "4", "{port}"], NO_SLAVES, id="master-no-slave"
        ),
        pytest.param(
            ["-t", "4", "-c", "0a", "{port}"], ONE_SLAVE, id="rs485-command"
        ),
        pytest.param(
            ["-t", "2", "-c", "0a", "{port}"], ONE_SLAVE, id="rs232-command"
        ),
        pytest.param(
            ["-m", "-t", "4", "-s", "1,2", "-c", "0a", "{port}"],
            ONE_SLAVE,
            id="master-command-two-slaves",
        ),
    ],
)
def test_invalid_serial_combinations_are_usage_errors(
    usage_error, serial_port, argv, message
):
    argv = [a.format(port=serial_port) for a in argv]

    assert usage_error(*argv) == f"{message}\n"


# the exit code of the program


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(["-c", "xyz"], "Invalid command: xyz", id="command"),
        pytest.param(["-s", "xyz"], "Invalid slave ID: xyz", id="slave"),
        pytest.param(["-t", "x"], "invalid choice", id="type"),
        pytest.param(["-p", "80"], "unrecognized arguments", id="no-ports"),
        pytest.param(["-n", "01:40"], "unrecognized arguments", id="no-nadir"),
        pytest.param(["-t", "2"], NOT_SERIAL, id="rs232-on-stdin"),
        pytest.param(["-m"], RS485_ONLY, id="master"),
        pytest.param(["-c", "0a"], ONE_SLAVE, id="command"),
        pytest.param(
            ["-d", ""],
            "",
            id="empty-log-destination",
            marks=pytest.mark.xfail(strict=True, reason="Issue #40"),
        ),
    ],
)
def test_semonitor_exits_with_2_on_bad_arguments(run_semonitor, argv, message):
    result = run_semonitor(*argv)

    assert result.returncode == 2
    assert result.stdout.startswith(b"usage: ")
    assert message in result.stderr
