#!/usr/bin/env python3
"""Print selected data from a JSON file."""

import json
import sys
from pathlib import Path


def open_input(args):
    """
    Open the input.

    The input is the file named by the first argument, or stdin when there is none. A file that was asked for but
    cannot be opened is an error, it must not silently turn into reading stdin.

    Args:
        args: The positional command line arguments. The first one, if there is one, names the input file.

    Returns:
        The open input file, or sys.stdin when there is no argument.

    Raises:
        SystemExit: If the named file cannot be opened, with the error written to stderr and exit status 1.
    """
    if not args:
        return sys.stdin
    try:
        return Path(args[0]).open()
    except OSError as ex:
        sys.exit(f"{sys.argv[0]}: {ex}")


# get program arguments and options
in_file = open_input(sys.argv[1:])

# read the input
with in_file:
    json_str = in_file.readline()
    while json_str != "":
        in_dict = json.loads(json_str)
        if in_dict["inverters"] != {}:
            sys.stdout.write("Inverters\n")
            for inverter in sorted(in_dict["inverters"].keys()):
                inv_dict = in_dict["inverters"][inverter]
                sys.stdout.write(
                    f"  {inv_dict['Date']} {inv_dict['Time']} {inverter}"
                    f" Eday:{inv_dict['Eday']:9.2f}"
                    f" Pac:{inv_dict['Pac']:7.2f}"
                    f" Vac:{inv_dict['Vac']:6.2f}\n"
                )
        if in_dict["optimizers"] != {}:
            sys.stdout.write("Optimizers\n")
            for optimizer in sorted(in_dict["optimizers"].keys()):
                opt_dict = in_dict["optimizers"][optimizer]
                sys.stdout.write(
                    f"  {opt_dict['Date']} {opt_dict['Time']} {optimizer}"
                    f" Eday:{opt_dict['Eday']:7.2f}\n"
                )
        if in_dict["events"] != {}:
            sys.stdout.write("Events\n")
            for event in sorted(in_dict["events"].keys()):
                event_dict = in_dict["events"][event]
                sys.stdout.write(
                    f"  {event_dict['Date']} {event_dict['Time']} {event}\n"
                )
        json_str = in_file.readline()
