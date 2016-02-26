#!/usr/bin/python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

# Usage: semonitor [options] inFile [outFile]
#
# Arguments:
#   inFile           file or serial port to read
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
#   -l               send logging messages to stdout
#   -m               function as a SolarEdge master
#   -n ipaddr        use the specified address on the network
#   -o optfile       optimizer file to write
#   -s invAddrs      comma delimited list of SolarEdge slave inverter addresses
#   -v               verbose output
#   -x               halt on exception

# Examples:

import struct
import time
import threading

from seConf import *
from seFiles import *
from seMsg import *
from seData import *
from seSerial import *
from seNetwork import *

# process the input file
def readFile(inFile, outFile, invFile, optFile, jsonFile):
    global waiting
    try:
        if parsing:     # process solaredge messages
            if debugFiles: log("parsing", inFileName)
            readMsg(inFile)   # skip bytes until the start of the first message
            inputSeq = 1
            while waiting:
                msg = readMsg(inFile)
                logMsg("-->", inputSeq, msg, inFile.name)
                if outFile:
                    outFile.write(msg)
                    outFile.flush()
                try:
                    # parse the message header
                    (dataLen, invFrom, invTo, function, data) = parseMsg(msg)
                    # parse the data
                    if dataLen > 0:
                        if function == 0x0500:
                            convertDevice(data, invFile, optFile, jsonFileName)
                            if masterMode: sendMsg(msgSeq, invTo, invFrom, 0x0080)
                            writeJson()
                        elif function == 0x039f:
                            convertStatus(data)
                        else:   # unknown function type
                            raise Exception("Unknown function 0x%04x" % function)
                            logData(data)
                except Exception as ex:
                    log("Exception:", ex.args[0])
                    logData(msg)
                    if haltOnException:
                        raise
                inputSeq += 1
        else:   # read and write in bufSize chunks for speed
            if debugFiles: log("reading", inFileName)
            while waiting:
                msg = readBytes(inFile, bufSize)
                outFile.write(msg)
    except KeyboardInterrupt:
        waiting = False
        return    

# start a thread to send SolarEdge master messages
def startMaster():
    # master message thread
    def sendMasterMsg():
        msgSeq = 0
        function = 0x0302
        while waiting:
            msgSeq += 1
            for slaveAddr in slaveAddrs:
                sendMsg(msgSeq, masterAddr, int(slaveAddr, 16), 0x0302)
            time.sleep(masterMsgInterval)
    masterThread = threading.Thread(name=masterThreadName, target=sendMasterMsg)
    masterThread.start()
    if debugFiles: log("starting", masterThreadName)
        
if __name__ == "__main__":
    inFile = openInput()
    (outFile, invFile, optFile, jsonFile) = openOutFiles()
    if masterMode: startMaster()
    readFile(inFile, outFile, invFile, optFile, jsonFile)
    closeFiles(inFile, outFile, invFile, optFile, jsonFile)
    
