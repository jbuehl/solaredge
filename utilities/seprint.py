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
            print("Inverters")
            for inverter in sorted(inDict["inverters"].keys()):
                invDict = inDict["inverters"][inverter]
                print(
                    "  "
                    + invDict["Date"]
                    + " "
                    + invDict["Time"]
                    + " "
                    + inverter
                    + " "
                    + "Eday:%9.2f" % invDict["Eday"]
                    + " "
                    + "Pac:%7.2f" % invDict["Pac"]
                    + " "
                    + "Vac:%6.2f" % invDict["Vac"]
                )
        if inDict["optimizers"] != {}:
            print("Optimizers")
            for optimizer in sorted(inDict["optimizers"].keys()):
                optDict = inDict["optimizers"][optimizer]
                print(
                    "  "
                    + optDict["Date"]
                    + " "
                    + optDict["Time"]
                    + " "
                    + optimizer
                    + " "
                    + "Eday:%7.2f" % optDict["Eday"]
                )
        if inDict["events"] != {}:
            print("Events")
            for event in sorted(inDict["events"].keys()):
                eventDict = inDict["events"][event]
                print(
                    "  " + eventDict["Date"] + " " + eventDict["Time"] + " " + event
                )
        jsonStr = inFile.readline()
