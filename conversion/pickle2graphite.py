#!/usr/bin/env python3
"""
Send SolarEdge performance metrics to Graphite via the graphite/carbon pickle listener port.

graphite will accept batches of metrics (in a pickled nested list of tuples format) over a pickle listener port (usually
2004) as well as individual metric values, one at a time, over the (usually) 2003 port.

The `Pickle2Graphite` class converts a nested dictionary (such as produced by `json.loads` on some solaredge traffic
that has been processed by semonitor) into the nested list of tuples structure expected by carbon.  The `send` method
pickles it, adds the requisite header, and sends it to graphite.

You may need to adjust the delay parameter, depending upon the capacity and busyness of the graphite server.  I have
found 0.2 works fine **for me** in production mode, when I am "following" some existing metrics in real time, as the
solaredge inverter emits them, but I needed to increase it to as much as 5.0 the first time I sent a new batch of metrics
to graphite, otherwise the carbon listener seemed to be swamped and didn't have time to create all the new metrics.
To be completely precise, I had problems when I sent an existing batch of metrics to a new "test"  base, which meant
graphite / carbon had to create a whole lot of new whisper files all at once.
"""

import json
import getopt
import time
import sys
import socket
import struct
import pickle
from common import unwrap_metricsDict

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
# Port must be the port which graphite (carbon) has configured to be the pickle listener port.
# The usual graphite installation default is 2004.
port = 2004
devices = ["inverters", "optimizers"]
delay = .2
following = False

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "b:fh:p:")
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
    if opt[0] == "-f":
        following = True


def getJsonStr(inFile, following):
    jsonStr = inFile.readline()
    if jsonStr == "" and following:
        while jsonStr == "":
            #wait for more data
            time.sleep(delay)
            jsonStr = inFile.readline()
    return jsonStr


class Pickle2Graphite(list):
    """
    Convert a (json) nested dictionary of dictionaries of metrics into the list of tuples format expected by the
    graphite (carbon) pickle interface and send them off to carbon's pickle listener port.
    """

    def __init__(self, metricsDict, base):
        for baseName, devAttrs in unwrap_metricsDict(metricsDict):
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
                            # A nested tuple as per the expectations of the pickle graphite interface
                            self.append((fullName, (timeStamp,
                                                    str(devAttrs[devAttr]))))
                    except ValueError:
                        # It is not a numeric metric
                        pass

    def send(self, graphiteSocket):
        # Remove the non list attributes from self, to keep graphite (actually the carbon listener) happy.
        payload = pickle.dumps(list(self))
        header = struct.pack("!L", len(payload))
        # print len(payload)
        graphiteSocket.send(header + payload)
        time.sleep(delay)


if __name__ == "__main__":
    # Timeout if no connection after 10 seconds,
    #   in which case check that graphite is running, and the hostName and port is correct.
    socket.setdefaulttimeout(10.0)
    graphiteSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # NB `port` must be the carbon pickle port, usually 2004 is configured by default.
    graphiteSocket.connect((hostName, port))
    jsonStr = getJsonStr(inFile, following)
    while jsonStr != "":
        try:
            inDict = json.loads(jsonStr)
            pickle2graphite = Pickle2Graphite(inDict, base=base)
            pickle2graphite.send(graphiteSocket)
        except ValueError:
            log('WARNING json.loads had a problem with the following jsonStr\n',
                jsonStr, "\n", "=" * 80, "\n")
        jsonStr = getJsonStr(inFile, following)
    graphiteSocket.close()
