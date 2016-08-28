#!/usr/bin/env python

# send a SolarEdge performance metrics to Graphite

import json
import getopt
import time
import sys
import socket

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
        base = opt[1]+"."
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
        for devType in devices:
            for devId in inDict[devType].keys():
                devAttrs = inDict[devType][devId]
                # convert date and time to unix time
                (year, month, day ) = devAttrs["Date"].split("-")
                (hour, minute, second) = devAttrs["Time"].split(":")
                timeStamp = time.mktime((int(year), int(month), int(day), int(hour), int(minute), int(second), 0, 0, 0))
                # every attribute is a metric
                for devAttr in devAttrs.keys():
                    if devAttr != "Date" and devAttr != "Time":
                        metric = "%s.%s.%s.%s %s %d\n" % (base, devType, devId, devAttr, str(devAttrs[devAttr]), timeStamp)
                        graphiteSocket.send(metric)
                        time.sleep(delay)
        jsonStr = inFile.readline()
    graphiteSocket.close()

