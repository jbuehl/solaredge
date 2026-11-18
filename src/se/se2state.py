"""
Maintain a file containing the current state and selected statistics.

The state covers SolarEdge inverters and optimizers.
"""

import getopt
import json
import sys
import time
from pathlib import Path

from se.metrics import open_input


def sum_items(item_dict, item_attr):
    """
    Return the sum of an attribute over the items in a dictionary.

    The stats item is ignored.
    """
    item_sum = 0
    for item in item_dict:
        if item != "stats":
            item_sum += item_dict[item][item_attr]
    return item_sum


def avg_items(item_dict, item_attr):
    """
    Return the average of an attribute over the items in a dictionary.

    The stats item is ignored. Returns 0 when there are no items.
    """
    try:
        return sum_items(item_dict, item_attr) / (len(item_dict) - 1)
    except ZeroDivisionError:
        return 0


def write_state(state_dict, out_file_name):
    """Write the state dictionary to the state file as JSON."""
    with Path(out_file_name).open("w") as out_file:
        json.dump(state_dict, out_file)


def zero_stats():
    """Return the stats of an item with all values zeroed."""
    return {
        "Vac": 0.0,
        "Pac": 0.0,
        "Eac": 0.0,
        "Eday": 0.0,
        "Etot": 0.0,
        "Temp": 0.0,
    }


def initial_state(inverters):
    """
    Return a state dictionary with all statistics zeroed.

    Args:
        inverters: The names of the inverters to add to the state.

    Returns:
        The new state dictionary.
    """
    state_dict = {
        "inverters": {"stats": zero_stats()},
        "optimizers": {"stats": {"Temp": 0.0}},
    }
    for inverter in inverters:
        state_dict["inverters"]["stats"][inverter] = zero_stats()
    return state_dict


def update_state(state_dict, in_dict):
    """
    Update the state dictionary in place with one line of input.

    Args:
        state_dict: The state dictionary to update.
        in_dict: The input data, with the inverters, optimizers and events.
    """
    state_dict["inverters"].update(in_dict["inverters"])
    state_dict["optimizers"].update(in_dict["optimizers"])
    # compute optimizer power
    for optimizer in state_dict["optimizers"]:
        if optimizer != "stats":
            state_dict["optimizers"][optimizer]["Pdc"] = (
                state_dict["optimizers"][optimizer]["Vmod"]
                * state_dict["optimizers"][optimizer]["Imod"]
            )
    # compute the stats
    state_dict["inverters"]["stats"]["Vac"] = avg_items(
        state_dict["inverters"], "Vac"
    )
    state_dict["inverters"]["stats"]["Pac"] = sum_items(
        state_dict["inverters"], "Pac"
    )
    state_dict["inverters"]["stats"]["Eac"] = sum_items(
        state_dict["inverters"], "Eac"
    )
    e_day = sum_items(state_dict["inverters"], "Eday")
    # only update Eday if it increases
    state_dict["inverters"]["stats"]["Eday"] = max(
        state_dict["inverters"]["stats"]["Eday"], e_day
    )
    state_dict["inverters"]["stats"]["Etot"] = sum_items(
        state_dict["inverters"], "Etot"
    )
    state_dict["inverters"]["stats"]["Temp"] = avg_items(
        state_dict["inverters"], "Temp"
    )
    state_dict["optimizers"]["stats"]["Temp"] = avg_items(
        state_dict["optimizers"], "Temp"
    )
    # zero current energy and power for devices when an event occurs
    if len(in_dict["events"]) != 0:
        for inverter in state_dict["inverters"]:
            state_dict["inverters"][inverter]["Eac"] = 0.0
            state_dict["inverters"][inverter]["Pac"] = 0.0
        for optimizer in state_dict["optimizers"]:
            state_dict["optimizers"][optimizer]["Vmod"] = 0.0
            state_dict["optimizers"][optimizer]["Vopt"] = 0.0
            state_dict["optimizers"][optimizer]["Imod"] = 0.0


def main(argv=None):
    """
    Maintain the state file with the given arguments.

    Args:
        argv: The command line arguments, without the program name. The arguments of the process are used when
            this is None.
    """
    initialize = False

    # get program arguments and options
    (opts, args) = getopt.getopt(sys.argv[1:] if argv is None else argv, "i:o:")
    in_file = open_input(args)
    for opt in opts:
        if opt[0] == "-i":
            initialize = True
            inverters = opt[1].split(",")
        if opt[0] == "-o":
            out_file_name = opt[1]

    # initialize the state dictionary
    if initialize:
        # zero the statistics
        state_dict = initial_state(inverters)
        write_state(state_dict, out_file_name)
    else:
        # start with values from the file if it exists
        try:
            with Path(out_file_name).open() as state_file:
                state_dict = json.load(state_file)
        except OSError:
            pass

    # read the input forever
    with in_file:
        while True:
            json_str = ""
            # wait for data
            while json_str == "":
                time.sleep(0.1)
                json_str = in_file.readline()
            update_state(state_dict, json.loads(json_str))
            write_state(state_dict, out_file_name)


if __name__ == "__main__":
    main()
