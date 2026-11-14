"""
SolarEdge command line argument parsing and validation.

Defines the run mode derived from the arguments, and parses and validates
the command line.
"""

import argparse
import datetime as dt
import logging
import logging.handlers
import re
import sys
from collections import namedtuple

import serial.tools.list_ports

import se.logutils

logger = logging.getLogger(__name__)

# local time of day for the daily exit when -n is given 'default'
NADIR_DEFAULT = dt.time(1, 40)
# nadir given as 'event': exit on the inverter's end-of-day event instead of a time
NADIR_EVENT = "event"

# run environment that is derived from the arguments that defines how the program will behave
RunMode = namedtuple(
    "RunMode",
    (
        "serialDevice",  # boolean
        "serialType",  # serial device type: "2" or "4"
        "passiveMode",  # boolean
        "masterMode",  # boolean
        "following",  # boolean
    ),
)


class SeArgumentParser(argparse.ArgumentParser):
    """Argument parser that prints its usage and exits on errors."""

    def error(self, message):
        """Print the usage, write the message to stderr and exit with status 2."""
        self.print_usage()
        sys.stderr.write(message + "\n")
        sys.exit(2)


def validated_commands(command_str):
    """
    Split and validate a "/"-separated list of commands.

    Each command is a hex function code, optionally followed by
    comma-separated typed hex parameters (e.g. "10,b01,h0002").

    Raises:
        argparse.ArgumentTypeError: If a command is malformed.
    """
    commands = []
    for c in command_str.split("/"):
        if not re.match(r"^[0-9a-fA-F]+(,[bhlBHL][0-9a-fA-F]+)*$", c):
            msg = f"Invalid command: {c}"
            raise argparse.ArgumentTypeError(msg)
        commands.append(c.split(","))
    return commands


def validated_slaves(slave_str):
    """
    Split and validate a comma-separated list of hex slave IDs.

    Raises:
        argparse.ArgumentTypeError: If a slave ID is not hexadecimal.
    """
    slaves = []
    for s in slave_str.split(","):
        if not re.match(r"^[0-9a-fA-F]+$", s):
            msg = f"Invalid slave ID: {s}"
            raise argparse.ArgumentTypeError(msg)
        slaves.append(s)
    return slaves


def validated_nadir(time_str):
    """
    Validate the time of day to exit at, given as HH:MM, "default" or "event".

    Returns:
        The default time, the string "event" for the inverter's end-of-day
        event, or the given time as a time of day.

    Raises:
        argparse.ArgumentTypeError: If the time is not valid.
    """
    if time_str.lower() == "default":
        return NADIR_DEFAULT
    if time_str.lower() == NADIR_EVENT:
        return NADIR_EVENT
    m = re.match(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$", time_str)
    if not m:
        msg = (
            "Invalid nadir, expected 24h HH:MM, 'default' or 'event': "
            f"{time_str}"
        )
        raise argparse.ArgumentTypeError(msg)
    return dt.time(int(m.group(1)), int(m.group(2)))


# the parser of the command line
def _make_parser():
    parser = SeArgumentParser(
        description="Parse Solaredge data to extract inverter and optimizer telemetry",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-a",
        dest="append",
        action="store_true",
        default=False,
        help="append to existing output files",
    )
    parser.add_argument(
        "-b",
        dest="baudrate",
        type=int,
        default=115200,
        help="baud rate for serial data source",
    )
    parser.add_argument(
        "-c",
        dest="commands",
        type=validated_commands,
        default=[],
        help="send the specified command functions",
    )
    parser.add_argument(
        "-d",
        dest="logfile",
        default="stderr",
        help="Where to write log messages: either a file name or one of ['stderr', 'syslog'].",
    )
    parser.add_argument(
        "-f",
        dest="follow",
        action="store_true",
        default=False,
        help="Wait for appended data as the input file grows (as in tail -f).",
    )
    parser.add_argument(
        "-m",
        dest="master",
        action="store_true",
        default=False,
        help="function as an RS485 master",
    )
    parser.add_argument(
        "-o",
        dest="outfile",
        default="stdout",
        help=(
            "Write performance data to the specified file in JSON format "
            "(default: stdout). Supports __date__ and __datetime__."
        ),
    )
    parser.add_argument(
        "-r",
        dest="record",
        help="file to record all incoming and outgoing messages to. Supports __date__ and __datetime__.",
    )
    parser.add_argument(
        "-n",
        dest="nadir",
        type=validated_nadir,
        default=None,
        metavar="HH:MM|default|event",
        help="exit daily at local HH:MM ('default' 01:40) or on the inverter end-of-day 'event'",
    )

    parser.add_argument(
        "-s",
        dest="slaves",
        type=validated_slaves,
        default=[],
        help="comma-delimited list of SolarEdge slave inverter IDs",
    )
    parser.add_argument(
        "-t",
        dest="type",
        choices=["2", "4"],
        help="serial data source type (2=RS232, 4=RS485)",
    )
    parser.add_argument(
        "-v", dest="verbose", action="count", default=0, help="verbose output"
    )
    parser.add_argument(
        "-x",
        dest="xerror",
        action="store_true",
        default=False,
        help="halt on data exception",
    )
    parser.add_argument(
        "datasource",
        default="stdin",
        nargs="?",
        help="input filename or serial port",
    )
    return parser


# configure the logging of the root logger
def _configure_logging(args):
    stream_formatter = logging.Formatter("%(message)s")
    file_formatter = logging.Formatter(
        "%(asctime)s %(message)s", datefmt="%b %d %H:%M:%S"
    )

    if args.logfile == "syslog":
        handler = logging.handlers.SysLogHandler(address="/dev/log")
        handler.setFormatter(stream_formatter)
    elif args.logfile == "stderr":
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(stream_formatter)
    elif args.logfile == "stdout":
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(stream_formatter)
    elif args.logfile:
        handler = logging.FileHandler(
            args.logfile, mode="a" if args.append else "w"
        )
        handler.setFormatter(file_formatter)

    level = {  # -v count -> log level (old option names in the comments)
        1: logging.INFO,  # -v    debugFiles
        2: logging.DEBUG,  # -vv   debugMsgs
        3: se.logutils.LOG_LEVEL_DATA,  # -vvv  debugData
        4: se.logutils.LOG_LEVEL_RAW,  # -vvvv debugRaw
    }.get(min(args.verbose, 4), logging.ERROR)

    # configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


# find out if the data source is a serial device
def _is_serial_device(args):
    serial_device = False
    if args.datasource == "-":
        args.datasource = "stdin"
    elif args.datasource != "stdin":
        # figure out the list of valid serial ports on this server
        # this is either a list of tuples or ListPortInfo objects
        serial_ports = serial.tools.list_ports.comports()
        serial_port_names = (
            (
                p.device
                if isinstance(p, serial.tools.list_ports_common.ListPortInfo)
                else p[0]
            )
            for p in serial_ports
        )
        serial_device = args.datasource in serial_port_names
    return serial_device


# validate the serial device
# NB The mode of an RS232 device is not made active here, see Issue #12
def _validate_serial(parser, args, *, serial_device):
    if serial_device:
        args.following = True
        if args.type not in ["2", "4"]:
            parser.error(
                "Input device type 2 or 4 must be specified for serial device"
            )
    elif args.type in ["2", "4"]:
        parser.error(
            args.datasource
            + " is not a valid serial device"
            + "\n"
            + "Input device types 2 and 4 are only valid for a serial device"
        )


# validate the master and command mode, and return if the mode is passive
def _validate_mode(parser, args):
    if args.master:
        passive_mode = False
        if args.type != "4":
            parser.error("Master mode only allowed with RS485 serial device")
        if len(args.slaves) < 1:
            parser.error(
                "At least one slave address must be specified for master mode"
            )
    else:
        passive_mode = True

    # command mode validation
    if args.commands:
        passive_mode = False
        if len(args.slaves) != 1:
            parser.error(
                "Exactly one slave address must be specified for command mode"
            )
    return passive_mode


# print out the arguments and options
def _log_arguments(args):
    for k, v in sorted(vars(args).items()):
        shown = v
        if k == "commands":
            shown = " ".join(
                ",".join(cpart for cpart in command) for command in v
            )
        if k == "slaves":
            shown = ",".join(slave for slave in v)
        logger.info("%s: %s", k, shown)


def get_args(argv=None):
    """
    Get the arguments from the command line, or argv, and validate them.

    Also configures logging from the verbosity option.

    Args:
        argv: The arguments to parse, those of the process when not given.

    Returns:
        A tuple (args, mode), where args is the parsed namespace and mode is
        the RunMode derived from it.
    """
    parser = _make_parser()
    args = parser.parse_args(argv)
    _configure_logging(args)
    serial_device = _is_serial_device(args)
    _validate_serial(parser, args, serial_device=serial_device)
    passive_mode = _validate_mode(parser, args)
    _log_arguments(args)

    return (
        args,
        RunMode(
            serial_device, args.type, passive_mode, args.master, args.follow
        ),
    )
