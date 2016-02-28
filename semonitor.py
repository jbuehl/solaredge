#!/usr/bin/python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

# Usage: semonitor [options] dataFile [outFile]
#
# Arguments:
#   dataFile         Input file or serial port to read
#                    If a serial port is specified, monitor the data in real time.
#                    If no file is specified, the program reads from stdin.
#                    If a file is specified, the program processes the data in that file and
#                    terminates, unless the -f option is specified, in which case it waits for 
#                    further data to be written to the file.
#
#   outFile          Optional file to copy input data to
#
# Options:
#   -a               append to inverter, optimizer, and output files
#   -b               baud rate for serial input (default: 115200)
#   -D delim         inverter and optimizer file delimiter (default: ",")
#   -f               output appended data as the input file grows (as in tail -f)
#   -H               write column headers to inverter and optimizer files
#   -i invfile       inverter file to write
#   -j jsonfile      json file to write current values to
#   -l               send log messages to stdout
#   -m               function as a SolarEdge master
#   -n interface     use the specified network interface
#   -o optfile       optimizer file to write
#   -s invdddrs      comma delimited list of SolarEdge slave inverter addresses
#   -v               verbose output
#   -x               halt on data exception

# Examples:

import struct
import time
import threading

from seConf import *
from seFiles import *
from seMsg import *
from seData import *

threadLock = threading.Lock()

# process the input data
def readData(dataFile, outFile, invFile, optFile, jsonFileName):
#    if parsing:     # process solaredge messages
        if debugFiles: log("parsing", dataFile.name)
        if not masterMode:
            readMsg(dataFile)   # skip data until the start of the first message
        while True:
            msg = readMsg(dataFile)
            if msg == "":   # end of file
                return
            if outFile:
                outFile.write(msg)
                outFile.flush()
            with threadLock:
                try:
                    # parse the message header
                    (msgSeq, fromAddr, toAddr, function, data) = parseMsg(msg)
                    # parse the data
                    if function == 0x0500:
                        convertDevice(data, invFile, optFile, jsonFileName)
                        if masterMode:
                            sendMsg(dataFile, formatMsg(msgSeq, toAddr, fromAddr, 0x0080))
                    elif function == 0x039f:
                        convertStatus(data)
                    elif function in [0x0090, 0x0503, 0x003d, 0x0080]:
                        logData(data)
                    else:   # unknown function type
                        raise Exception("Unknown function 0x%04x" % function)
                        logData(data)
                except Exception as ex:
                    log("Exception:", ex.args[0])
                    logData(msg)
                    if haltOnException:
                        raise
#    else:   # read and write in bufSize chunks for speed
#        if debugFiles: log("reading", dataFile.name)
#        while True:
#            msg = readBytes(dataFile, bufSize)
#            if msg == "":   # end of file
#                return
#            outFile.write(msg)

# master commands thread
def sendCommands(dataFile):
    msgSeq = 0
    function = 0x0302
    while True:
        msgSeq += 1
        for slaveAddr in slaveAddrs:
            with threadLock:
                sendMsg(dataFile, formatMsg(msgSeq, masterAddr, int(slaveAddr, 16), 0x0302))
        time.sleep(masterMsgInterval)

# set the inverter mode to 0 and restart it
def restartInverter(dataFile):
    slaveAddr = int(slaveAddrs[0], 16)
    sendMsg(dataFile, formatMsg(1001, masterAddr, slaveAddr, 0x0012, struct.pack("<H", 0x0329)))
    parseMsg(readMsg(dataFile))
    sendMsg(dataFile, formatMsg(1002, masterAddr, slaveAddr, 0x0011, struct.pack("<HL", 0x0329, 0)))
    parseMsg(readMsg(dataFile))
    sendMsg(dataFile, formatMsg(1003, masterAddr, slaveAddr, 0x0030, struct.pack("<HL", 0x01f4, 0)))
    parseMsg(readMsg(dataFile))
            
if __name__ == "__main__":
    dataFile = openData(inFileName)
    (outFile, invFile, optFile) = openFiles(outFileName, invFileName, optFileName, jsonFileName)
    if restart:
        restartInverter(dataFile)
    elif masterMode:
        readThread = threading.Thread(name=readThreadName, target=readData, args=(dataFile, outFile, invFile, optFile, jsonFileName))
        readThread.start()
        if debugFiles: log("starting", readThreadName)
        masterThread = threading.Thread(name=masterThreadName, target=sendCommands, args=(dataFile,))
        masterThread.start()
        if debugFiles: log("starting", masterThreadName)
    else:
        readData(dataFile, outFile, invFile, optFile, jsonFileName)
    closeFiles(outFile, invFile, optFile)
    
