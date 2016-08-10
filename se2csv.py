#!/usr/bin/python

# Convert SolarEdge inverter performance monitoring data from JSON to CSV

import getopt
import json
import sys

from seDataParams import *

# file parameters
inFileName = ""
invFileName = ""
optFileName = ""
headers = False
delim = ","
writeMode = "w"
invSeq = 0
optSeq = 0

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

# open the output files
def openOutFiles(invFileName, optFileName):
    invFile = openOutFile(invFileName, writeMode)
    optFile = openOutFile(optFileName, writeMode)
    return (invFile, optFile)
    
# close output files        
def closeOutFiles(invFile, optFile):
    if invFile:
        invFile.close()
    if optFile:
        optFile.close()

# write output file headers
def writeHeaders(outFile, items):
    outFile.write(delim.join(item for item in items)+"\n")

# write data to output files
def writeData(msgDict, invFile, optFile):
    global invSeq, optSeq
    if invFile:
        if headers and (invSeq == 0) and (msgDict["inverters"] != {}):
            writeHeaders(invFile, invItems)
        for seId in msgDict["inverters"].keys():
            invSeq = writeDevData(invFile, invOutFmt, msgDict["inverters"][seId], invItems, invSeq)
    if optFile:
        if headers and (optSeq == 0) and (msgDict["optimizers"] != {}):
            writeHeaders(optFile, optItems)
        for seId in msgDict["optimizers"].keys():
            optSeq = writeDevData(optFile, optOutFmt, msgDict["optimizers"][seId], optItems, optSeq)

# write device data to output file
def writeDevData(outFile, outFmt, devDict, devItems, devSeq):
    if outFile:
        outMsg = delim.join([(outFmt[i] % devDict[devItems[i]]) for i in range(len(devItems))])
        devSeq += 1
        outFile.write(outMsg+"\n")
    return devSeq

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "ad:hi:o:")

try:
    inFileName = args[0]
except:
    inFileName = "stdin"
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

# process the data
inFile = openInput(inFileName)
(invFile, optFile) = openOutFiles(invFileName, optFileName)
for jsonStr in inFile:
    try:
        writeData(json.loads(jsonStr), invFile, optFile)
    except ValueError:
        print jsonStr
closeInput(inFile)
closeOutFiles(invFile, optFile)
    

