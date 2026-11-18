#!/usr/bin/env python3
"""Send SolarEdge performance metrics to Graphite."""

import getopt
import json
import math
import socket
import sys
import time

from common import open_input, unwrap_metrics_dict

try:
    import syslog
except ImportError:
    # Allow for the fact that syslog is not (to my knowledge) available on Windows
    import seWindowsSyslog as syslog


def log(*args):
    """Log a message, made of the space separated arguments, to syslog."""
    message = args[0] + " "
    for arg in args[1:]:
        message += arg.__str__() + " "
    # TODO: Make this align better with the multiple logging options available elsewhere in semonitor
    syslog.syslog(message)


# parameter defaults
base = ""
host_name = "localhost"
port = 2003
devices = ["inverters", "optimizers"]
delay = 0.1

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "b:h:p:")
in_file = open_input(args)
for opt in opts:
    if opt[0] == "-b":
        base = opt[1] + "."
    if opt[0] == "-h":
        host_name = opt[1]
    if opt[0] == "-p":
        port = int(opt[1])

if __name__ == "__main__":
    graphite_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    graphite_socket.connect((host_name, port))
    with in_file:
        json_str = in_file.readline()
        while json_str != "":
            in_dict = json.loads(json_str)
            for base_name, dev_attrs in unwrap_metrics_dict(in_dict):
                # convert date and time to unix time
                try:
                    (year, month, day) = dev_attrs["Date"].split("-")
                    (hour, minute, second) = dev_attrs["Time"].split(":")
                except KeyError:
                    log(
                        "Date or Time is missing or incorrectly formatted for this set of metrics"
                    )
                    (year, month, day, hour, minute, second) = (
                        1970,
                        1,
                        1,
                        0,
                        1,
                        1,
                    )
                # Set the dst parameter in mktime to -1, so that the system determines whether dst is in effect!
                # Without this, when dst is in effect, the timeStamp is 3600 seconds into the future!
                time_stamp = time.mktime(
                    (
                        int(year),
                        int(month),
                        int(day),
                        int(hour),
                        int(minute),
                        int(second),
                        0,
                        0,
                        -1,
                    )
                )
                # Treat every attribute as a metric - except for non-numeric ones!
                for dev_attr in dev_attrs:
                    if dev_attr not in {"Date", "Time", "Undeciphered_data"}:
                        try:
                            # Weed out attributes with non numeric values (Graphite does this too, but why clog the
                            # network?)
                            test = float(dev_attrs[dev_attr])
                            if math.isnan(test):
                                # It's a NaN!
                                pass
                            else:
                                full_name = f"{base}{base_name}.{dev_attr}"
                                metric = f"{full_name} {dev_attrs[dev_attr]!s} {time_stamp}\n"
                                graphite_socket.send(metric)
                                time.sleep(delay)
                        except ValueError:
                            # It's not a numeric metric, ignore it
                            pass
            json_str = in_file.readline()
    graphite_socket.close()
