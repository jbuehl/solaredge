#!/usr/bin/env python

# Maintain a file containing the current state and selected statistics 
# of SolarEdge inverters and optimizers

import json
import getopt
import time
import sys

initialize = False

# return the sum of the specified attribute of the items in the specified dictionary
# ignore the stats item
def sumItems(itemDict, itemAttr):
    itemSum = 0
    for item in itemDict.keys():
        if item != "stats":
            itemSum += itemDict[item][itemAttr]
    return itemSum

# return the average of the specified attribute of the items in the specified dictionary
# ignore the stats item
def avgItems(itemDict, itemAttr):
    try:
        return sumItems(itemDict, itemAttr)/(len(itemDict) - 1)
    except ZeroDivisionError:
        return 0
            
# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "i:o:")
try:
    inFile = open(args[0])
except:
    inFile = sys.stdin
for opt in opts:
    if opt[0] == "-i":
        initialize = True
        inverters = opt[1].split(",")
    if opt[0] == "-o":
        outFileName = opt[1]
        
# initialize the state dictionary
if initialize:
    # zero the statistics
    stateDict = {"inverters": 
                    {"stats": {"Vac": 0.0, "Pac":0.0, "Eac":0.0, "Eday": 0.0, "Etot": 0.0, "Temp": 0.0}}, 
                "optimizers": 
                    {"stats": {"Temp": 0.0}}}
    for inverter in inverters:
        stateDict["inverters"]["stats"][inverter] = {"Vac":0.0, "Pac":0.0, "Eac":0.0, "Eday":0.0, "Etot": 0.0, "Temp": 0.0}
else:
    # start with values from the file if it exists
    try:
        with open(outFileName) as stateFile:
            stateDict = json.load(stateFile)
    except IOError:
        pass
        
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
    # compute the stats
    stateDict["inverters"]["stats"]["Vac"] = avgItems(stateDict["inverters"], "Vac")
    stateDict["inverters"]["stats"]["Pac"] = sumItems(stateDict["inverters"], "Pac")
    stateDict["inverters"]["stats"]["Eac"] = sumItems(stateDict["inverters"], "Eac")
    stateDict["inverters"]["stats"]["Eday"] += sumItems(inDict["inverters"], "Eac")
    stateDict["inverters"]["stats"]["Etot"] = sumItems(stateDict["inverters"], "Etot")
    stateDict["inverters"]["stats"]["Temp"] = avgItems(stateDict["inverters"], "Temp")
    stateDict["optimizers"]["stats"]["Temp"] = avgItems(stateDict["optimizers"], "Temp")
    # zero current energy and power for devices when an event occurs
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
