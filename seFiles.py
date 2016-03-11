# SolarEdge input data and file management

import serial
import sys
import socket
from seConf import *
from seNetwork import *

# open data socket and wait for connection from inverter
def openDataSocket():
    try:
        dataSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dataSocket.bind(("", sePort))
        dataSocket.listen(0)        
        (clientSocket, addr) = dataSocket.accept()
        debug("debugFiles", "connection from", addr[0]+":"+str(addr[1]))
        return clientSocket.makefile("rwb")
    except:
        terminate(1, "Unable to open data socket")

# open serial device    
def openSerial(inFileName):
    try:
        return serial.Serial(inFileName, baudrate=baudRate)
    except:
        terminate(1, "Unable to open "+inFileName)
        
def openInFile(inFileName):
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
    if networkDevice:
        if networkSvcs:
            # start network services
            startDhcp()
            startDns()
        return openDataSocket()
    elif serialDevice:
        return openSerial(inFileName)
    else:
        return openInFile(inFileName)

# close the data source
def closeData(dataFile):
    if networkDevice:
        dataFile._sock.close()
    dataFile.close()

# open in output file if it is specified
def openOutFile(fileName, writeMode="w"):
    if fileName != "":
        try:
            return open(fileName, writeMode)
            debug("debugFiles", "writing", fileName)
        except:
            terminate(1, "Unable to open "+fileName)
    else:
        return None

# open the output files
def openOutFiles(outFileName, invFileName, optFileName, jsonFileName):
    outFile = openOutFile(outFileName, writeMode)
    invFile = openOutFile(invFileName, writeMode)
    optFile = openOutFile(optFileName, writeMode)
    jsonFile = openOutFile(jsonFileName, writeMode)
    return (outFile, invFile, optFile, jsonFile)
    
# close output files        
def closeOutFiles(outFile, invFile, optFile, jsonFile):
    if outFile: outFile.close()
    if invFile: invFile.close()
    if optFile: optFile.close()
    if jsonFile: jsonFile.close()

