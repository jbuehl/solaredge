#!/usr/bin/env python

# print(selected data from a JSON file

import json
import sys

# get program arguments and options
try:
    inFile = open(sys.argv[1])
except:
    inFile = sys.stdin

# read the input
jsonStr = inFile.readline()
while jsonStr != "":
    inDict = json.loads(jsonStr)
    if inDict["inverters"] != {}:
        print("Inverters")
        for inverter in sorted(inDict["inverters"].keys()):
            invDict = inDict["inverters"][inverter]
            print("  "+invDict["Date"]+" "+invDict["Time"]+" "+inverter+" "+"Eday:%9.2f"%invDict["Eday"]+" "+"Pac:%7.2f"%invDict["Pac"]+" "+"Vac:%6.2f"%invDict["Vac"])
    if inDict["optimizers"] != {}:
        print("Optimizers")
        for optimizer in sorted(inDict["optimizers"].keys()):
            optDict = inDict["optimizers"][optimizer]
            print("  "+optDict["Date"]+" "+optDict["Time"]+" "+optimizer+" "+"Eday:%7.2f"%optDict["Eday"])
    if inDict["events"] != {}:
        print("Events")
        for event in sorted(inDict["events"].keys()):
            eventDict = inDict["events"][event]
            print("  "+eventDict["Date"]+" "+eventDict["Time"]+" "+event)
    jsonStr = inFile.readline()
