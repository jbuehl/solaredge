# SolarEdge input data and output file management

import serial
import sys
import socket

from seConf import *

# open data socket and wait for connection from inverter
def openDataSocket():
    try:
        dataSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dataSocket.bind(("", sePort))
        dataSocket.listen(5)        
        (clientSocket, addr) = dataSocket.accept()
        debug("debugFiles", "connection from", addr[0]+":"+str(addr[1]))
        return clientSocket.makefile()
    except:
        terminate(1, "Unable to open data socket")

# open serial device    
def openSerial(inFileName):
    try:
        return serial.Serial(inFileName, baudrate=baudRate)
    except:
        terminate(1, "Unable to open "+inFileName)
        
def openFile(inFileName):
    try:
        if inFileName == "stdin":
            return sys.stdin
        else:
            return open(inFileName)
    except:
        terminate(1, "Unable to open "+inFileName)

# open the specified data source
def openData(inFileName):
    if debugFiles: log("opening", inFileName)
    if networkMode:
        return openDataSocket()
    elif serialDevice:
        return openSerial(inFileName)
    else:
        return openFile(inFileName)

# open the output files if they are specified
def openFiles(outFileName, invFileName, optFileName, jsonFileName):
    outFile = None
    invFile = None
    optFile = None
    if outFileName != "":
        try:
            outFile = open(outFileName, writeMode)
            debug("debugFiles", "writing", outFileName)
        except:
            terminate(1, "Unable to open "+outFileName)
    if invFileName != "":
        try:
            invFile = open(invFileName, writeMode)
            if headers: writeHeaders(invFile, invItems, delim)
            debug("debugFiles", "writing", invFileName)
        except:
            terminate(1, "Unable to open "+invFileName)
    if optFileName != "":
        try:
            optFile = open(optFileName, writeMode)
            if headers: writeHeaders(optFile, optItems, delim)
            debug("debugFiles", "writing", optFileName)
        except:
            terminate(1, "Unable to open "+optFileName)
    if jsonFileName != "":
        try:
            jsonFile = open(jsonFileName, "w")
            jsonFile.close()    # don't leave this one open
            debug("debugFiles", "writing", jsonFileName)
        except:
            terminate(1, "Unable to open "+jsonFileName)
    return (outFile, invFile, optFile)
    
# close output files        
def closeFiles(outFile, invFile, optFile):
    if outFile: outFile.close()
    if invFile: invFile.close()
    if optFile: optFile.close()

