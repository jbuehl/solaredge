#!/usr/bin/env python

# send a SolarEdge performance metrics to Graphite

import json
import getopt
import time
import sys
import socket
from seDataDevices import unwrap_metricsDict

try:
    import syslog
except ImportError:
    # Allow for the fact that syslog is not (to my knowledge) available on Windows
    import seWindowsSyslog as syslog


# log a message to syslog
def log(*args):
    message = args[0] + " "
    for arg in args[1:]:
        message += arg.__str__() + " "
    # todo : Make this align better with the multiple logging options available elsewhere in semonitor
    syslog.syslog(message)


# parameter defaults
base = ""
hostName = "localhost"
port = 2003
devices = ["inverters", "optimizers"]
delay = .1

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "b:h:p:")
try:
    inFile = open(args[0])
except:
    inFile = sys.stdin
for opt in opts:
    if opt[0] == "-b":
        base = opt[1] + "."
    if opt[0] == "-h":
        hostName = opt[1]
    if opt[0] == "-p":
        port = int(opt[1])

if __name__ == "__main__":
    graphiteSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    graphiteSocket.connect((hostName, port))
    jsonStr = inFile.readline()
    while jsonStr != "":
        inDict = json.loads(jsonStr)
        for baseName, devAttrs in unwrap_metricsDict(inDict):
            # convert date and time to unix time
            try:
                (year, month, day) = devAttrs["Date"].split("-")
                (hour, minute, second) = devAttrs["Time"].split(":")
            except KeyError:
                log("Date or Time is missing or incorrectly formatted for this set of metrics"
                    )
                (year, month, day, hour, minute, second) = (1970, 01, 01, 00,
                                                            01, 01)
            # Set the dst parameter in mktime to -1, so that the system determines whether dst is in effect!
            # Without this, when dst is in effect, the timeStamp is 3600 seconds into the future!
            timeStamp = time.mktime((int(year), int(month),
                                     int(day), int(hour), int(minute),
                                     int(second), 0, 0, -1))
            # Treat every attribute as a metric - except for non-numeric ones!
            for devAttr in devAttrs.keys():
                if devAttr != "Date" and devAttr != "Time" and devAttr != 'Undeciphered_data':
                    try:
                        # Weed out attributes with non numeric values (graphite does this too, but why clog the network?)
                        test = float(devAttrs[devAttr])
                        if test != test:
                            # It's a nan!
                            pass
                        else:
                            fullName = "{}{}.{}".format(
                                base, baseName, devAttr)
                            metric = "{} {} {}\n".format(
                                fullName, str(devAttrs[devAttr]), timeStamp)
                            graphiteSocket.send(metric)
                            time.sleep(delay)
                    except ValueError:
                        # It's not a numeric metric, ignore it
                        pass
        jsonStr = inFile.readline()
    graphiteSocket.close()
