#!/usr/bin/python

# Maintain a file containing the current state of SolarEdge inverters and optimizers

import json
import getopt
import time
import sys

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "o:")
try:
    inFile = open(args[0])
except:
    inFile = sys.stdin
for opt in opts:
    if opt[0] == "-o":
        outFileName = opt[1]
        
# initialize the state from the file if it exists
try:
    with open(outFileName) as stateFile:
        stateDict = json.load(stateFile)
except:
    stateDict = {"inverters": {}, "optimizers": {}}
        
# read the input forever
while True:
    jsonStr = ""
    # wait for data
    while jsonStr == "":
        time.sleep(.1)
        jsonStr = inFile.readline()
    inDict = json.loads(jsonStr)
    # update the state values
    stateDict["inverters"].update(inDict["inverters"])
    stateDict["optimizers"].update(inDict["optimizers"])
    # zero current energy and power when an event occurs
    if len(inDict["events"]) != 0:
        for inverter in stateDict["inverters"].keys():
            stateDict["inverters"][inverter]["Eac"] = 0.0
            stateDict["inverters"][inverter]["Pac"] = 0.0
        for optimizer in stateDict["optimizers"].keys():
            stateDict["optimizers"][optimizer]["Vmod"] = 0.0
            stateDict["optimizers"][optimizer]["Vopt"] = 0.0
            stateDict["optimizers"][optimizer]["Imod"] = 0.0
    # update the state file
    with open(outFileName, "w") as outFile:
        json.dump(stateDict, outFile)
