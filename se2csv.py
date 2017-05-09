#!/usr/bin/env python

# Convert SolarEdge inverter performance monitoring data from JSON to CSV

import getopt
import json
import sys

from seDataParams import *
from seDataDevices import ParseDevice
from seDataDevices import unwrap_metricsDict

# file parameters
devsFilePrefix = ""
devsFile = {}
eventsFileName = ""
headers = False
delim = ","
writeMode = "w"
devsSeq = {}
devsItems = {}

def openInFile(inFileName):
    if inFileName == "stdin":
        return sys.stdin
    else:
        return open(inFileName)

# open the specified input file
def openInput(inFileName):
    return openInFile(inFileName)

# close the input file
def closeInput(dataFile):
    dataFile.close()

# open in output file if it is specified
def openOutFile(fileName, writeMode="w"):
    if fileName != "":
        return open(fileName, writeMode)
    
# close output files        
def closeOutFiles(devsFile):
    for devFile in devsFile.itervalues():
        devFile.close()

# write output file headers
def writeHeaders(outFile, items):
    outFile.write(delim.join(item for item in items)+"\n")

# write data to output files
def writeData(msgDict, devsFilePrefix):
    global devsSeq, devsFile
    if devsFilePrefix:
        if msgDict != {}:
            for baseName, devAttrs in unwrap_metricsDict(msgDict):
                devName, devId = baseName.split(".", 1)
                if devName not in devsSeq.keys():
                    # First time we've seen this devName, construct devsFileName entry and open the file
                    devsSeq[devName] = 0
                    devsFileName = '{}.{}.csv'.format(devsFilePrefix, devName)
                    devsFile[devName] = openOutFile(devsFileName, writeMode)
                    # Extract the list of item names for this devName
                    itemNames = get_device_items(devAttrs)
                    # Add deviceId to the start of list of itemNames to put into the csv file
                    itemNames.insert(0, "__Identifier__")
                    devsItems[devName] = itemNames
                    if headers:
                        writeHeaders(devsFile[devName], devsItems[devName])

                # Make sure __Identifer__ is actually stored in devAttrs
                devAttrs["__Identifier__"] = devId
                devsSeq[devName] = writeDevData(devsFile[devName],
                                                # todo Implement a more elegant way of building a generic format list
                                                ["%s"] * len(devsItems[devName]), #optOutFmt,
                                                devAttrs,
                                                devsItems[devName], devsSeq[devName])


def get_device_items(devAttrs):
    # Extract the list of item names for this devName
    # When the parsed data is reduced to reduced to json we lose the information about which subclass parsed it! :-(
    # So we have to examine the subclasses again.
    try:
        seType, devLen = get_device_header_details(devAttrs)
        for subclass in ParseDevice.__subclasses__():
            if subclass._dev == seType:
                return subclass.itemNames()
    except KeyError:
        pass
    # This won't work for the unrecognised devices which are parsed by the special ParseDevice_Explorer, because of the
    # way each instance generates (lots of) names when the __init__ method runs.
    # So, just get all the names from the json dictionary!  It's what I want when exploring a new device anyway.
    outItems = devAttrs.keys()
    outItems.sort()
    return outItems

def get_device_header_details(devAttrs):
    seType = int(devAttrs["seType"], 16)  # (At the moment) I am storing seType as a hex str
    devLen = devAttrs["devLen"]
    return seType, devLen


# write device data to output file
def writeDevData(outFile, outFmt, devDict, devItems, devSeq):
    if outFile:
        outMsg = delim.join([(outFmt[i] % devDict[devItems[i]]) for i in range(len(devItems))])
        devSeq += 1
        outFile.write(outMsg+"\n")
    return devSeq


# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "ad:hi:o:p:e:")

for opt in opts:
    if opt[0] == "-a":
        writeMode = "a"
    elif opt[0] == "-d":
        delim = opt[1]
    elif opt[0] == "-h":
        headers = True
    elif opt[0] == "-i":
        invFileName = opt[1]
    elif opt[0] == "-o":
        optFileName = opt[1]
    elif opt[0] == "-e":
        eventsFileName = opt[1]
    elif opt[0] == "-p":
        devsFilePrefix = opt[1]


if __name__ == "__main__":

    try:
        inFileName = args[0]
    except:
        inFileName = "stdin"

    # process the data
    inFile = openInput(inFileName)
    for jsonStr in inFile:
        try:
            writeData(json.loads(jsonStr), devsFilePrefix)
        except ValueError:
            print jsonStr
    closeInput(inFile)
    closeOutFiles(devsFile)


