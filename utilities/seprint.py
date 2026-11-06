#!/usr/bin/env python3

# print selected data from a JSON file

import json
import sys


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
        return open(args[0])
    except OSError as ex:
        sys.exit(f"{sys.argv[0]}: {ex}")


# get program arguments and options
inFile = open_input(sys.argv[1:])

# read the input
with inFile:
    jsonStr = inFile.readline()
    while jsonStr != "":
        inDict = json.loads(jsonStr)
        if inDict["inverters"] != {}:
            sys.stdout.write("Inverters\n")
            for inverter in sorted(inDict["inverters"].keys()):
                invDict = inDict["inverters"][inverter]
                sys.stdout.write(
                    f"  {invDict['Date']} {invDict['Time']} {inverter}"
                    f" Eday:{invDict['Eday']:9.2f}"
                    f" Pac:{invDict['Pac']:7.2f}"
                    f" Vac:{invDict['Vac']:6.2f}\n"
                )
        if inDict["optimizers"] != {}:
            sys.stdout.write("Optimizers\n")
            for optimizer in sorted(inDict["optimizers"].keys()):
                optDict = inDict["optimizers"][optimizer]
                sys.stdout.write(
                    f"  {optDict['Date']} {optDict['Time']} {optimizer}"
                    f" Eday:{optDict['Eday']:7.2f}\n"
                )
        if inDict["events"] != {}:
            sys.stdout.write("Events\n")
            for event in sorted(inDict["events"].keys()):
                eventDict = inDict["events"][event]
                sys.stdout.write(
                    f"  {eventDict['Date']} {eventDict['Time']} {event}\n"
                )
        jsonStr = inFile.readline()
