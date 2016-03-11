#!/usr/bin/python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

# Usage: python semonitor.py [options] dataFile [outFile]

# Arguments:
#   dataFile         Input filename or serial port
#                    If the filename is "-" or no filename is specified, the program reads from stdin.
#                    If a filename is specified, the program processes the data in that file and
#                    terminates, unless the -f option is specified, in which case it waits for 
#                    further data to be written to the file.
#                    If the filename corresponds to a serial port, process the data
#                    from that port.
#
#   outFile          Optional file to copy all incoming and outgoing messages to

# Options:
#   -a               append to inverter, optimizer, json, and output files
#   -b               baud rate for serial input (default: 115200)
#   -c cmd[/cmd/...] send the specified command sequence
#   -D delim         inverter and optimizer file delimiter (default: ",")
#   -f               output appended data as the input file grows (as in tail -f)
#   -H               write column headers to inverter and optimizer files
#   -i invfile       file to write inverter data to
#   -j jsonfile      json file to write data to
#   -l               send log messages to stdout
#   -m               function as a RS485 master
#   -n interface     run network services on the specified interface
#   -o optfile       file to write optimizer data to
#   -s invdddrs      comma delimited list of SolarEdge slave inverter addresses
#   -v               verbose output
#   -x               halt on data exception

# Notes:
#    Data may be read from a file containing messages in the SolarEdge protocol that was previously created by 
#    seextract.py from a pcap file, or the output from a previous run of semonitor.py.  It may also be
#    read in real time from one of the RS232, RS485, or ethernet interfaces on a SolarEdge inverter.
#
#    Messages are sent to the system log, unless the -l option is specified.  If an error occurs
#    while processing data, the program will log a message and continue unless the -x option is
#    specified.
#
#    The level of debug messaging is controlled using the -v option, which may be specified up to
#    4 times:
#        -v      log input parameters and file operations
#        -vv     log incoming and outgoing messages and their sizes
#        -vvv    log the parsed data of incoming and outgoing messages
#        -vvvv   log the raw data of incoming and outgoing messages
#
#    The -c, -m, and -s options are not meaningful if input is from a file or stdin.
#
#    The -m option is only valid if a serial port is specified and one or more inverter serial
#    numbers must be specified with the -s option.  If this option is specified, there cannot
#    be another master device on the RS485 bus.
#
#    The -c option may be specified for a serial device or the network.  The option specifies one
#    or more SolarEdge protocol command functions separated by a "/".  Each command function
#    consists of a hex function code followed by zero or more comma separated hex parameters.
#    Each parameter must begin with one of the letters "B", "H", or "L" to designate the
#    length of the parameter:
#        B = 8 bits
#        H = 16 bits
#        L = 32 bits
#    All function codes and parameters must be hexadecimal numbers, without the leading "0x".

# Examples:
#    # python semonitor.py -i yyyymmdd.inv -o yyyymmdd.opt -H yyyymmdd.se
#
#    Read from the file yyyymmdd.se and write inverter and optimizer data to the csv files
#    yyyymmdd.inv and yyyymmdd.opt with headers.
#
#    # python semonitor.py -j yyyymmdd.json yyyymmdd.se
#
#    Read from the file yyyymmdd.se and write data to the json file yyyymmdd.json.
#
#    # python seextract.py yyyymmdd.pcap | python semonitor.py -j yyyymmdd.json
#
#    Extract SolarEdge data from the file yyyymmdd.pcap and write data to the json file 
#    yyyymmdd.json.
#
#    # python semonitor.py -j yyyymmdd.json -m -s 7f101234,7f105678 COM4
#
#    Function as a RS485 master to request data from the inverters 7f101234 and 7f105678
#    using serial port COM4.
#
#    # python semonitor.py -c 0012,H0329 -s 7f101234 /dev/ttyUSB0
#
#    Send a command to the inverter 7f101234 to request the value of parameter 0x0329
#    using serial port /dev/ttyUSB0.
#
#    # python semonitor.py -c 0011,H329,L1/0012,H329/0030,H01f4,L0 -s 7f101234 /dev/ttyUSB0
#
#    Send commands to the inverter 7f101234 to set the value of parameter 0x0329 to 1,
#    followed by a command to reset the inverter using serial port /dev/ttyUSB0.
#
#    # sudo python semonitor.py -j yyyymmdd.json -n eth1
#
#    Start the dhcp and dns services on network interface eth1.  Accept connections
#    from inverters and function as a SolarEdge monitoring server.  Write performance
#    data to file yyyymmdd.json.

import time
import threading
from seConf import *
from seFiles import *
from seMsg import *
from seData import *
from seCommands import *

# global variables
threadLock = threading.Lock()
masterEvent = threading.Event()
running = True
inSeq = 0
outSeq = 0

# process the input data
def readData(dataFile, outFile, invFile, optFile, jsonFile):
    global inSeq, outSeq
    if updateFileName != "":    # create an array of zeros for the firmware update file
        updateBuf = list('\x00'*updateSize)
    if passiveMode:
        (msg, inSeq) = readMsg(dataFile, inSeq, outFile)   # skip data until the start of the first complete message
    while running:
        (msg, inSeq) = readMsg(dataFile, inSeq, outFile)
        if msg == "":   # end of file
            if updateFileName != "":    # write the firmware update file
                updateBuf = "".join(updateBuf)
#                print struct.unpack("<H", updateBuf[0:2])[0], calcCrc(updateBuf[12:struct.unpack("<L", updateBuf[4:8])[0]-4])
                with open("se.dat", "w") as updateFile:
                    updateFile.write(updateBuf)
            return
        if msg == "\x00"*len(msg):   # ignore messages containing all zeros
            if debugData: logData(msg)
        else:
            with threadLock:
                try:
                    # parse the message
                    (msgSeq, fromAddr, toAddr, function, data) = parseMsg(msg)
                    msgData = parseData(function, data)                    
                    if (function == PROT_CMD_SERVER_POST_DATA) and (data != ""):    # performance data
                        # write performance data to output files
                        writeData(msgData, invFile, optFile, jsonFile)
                    elif (updateFileName != "") and function == PROT_CMD_UPGRADE_WRITE:    # firmware update data
                        updateBuf[msgData["offset"]:msgData["offset"]+msgData["length"]] = msgData["data"]
                    if (networkDevice or masterMode):    # send reply
                        replyFunction = ""
                        if function == PROT_CMD_SERVER_POST_DATA:      # performance data
                            # send ack
                            replyFunction = PROT_RESP_ACK
                            replyData = ""
                        elif function == PROT_CMD_SERVER_GET_GMT:    # time request
                            # set time
                            replyFunction = PROT_RESP_SERVER_GMT
                            replyData = formatTime(int(time.time()), (time.localtime().tm_hour-time.gmtime().tm_hour)*60*60)
                        elif function == PROT_RESP_POLESTAR_MASTER_GRANT_ACK:   # RS485 master release
                            masterEvent.set()
                        if replyFunction != "":
                            msg = formatMsg(msgSeq, toAddr, fromAddr, replyFunction, replyData)
                            outSeq = sendMsg(dataFile, msg, outSeq, outFile)
                except Exception as ex:
                    debug("debugEnable", "Exception:", ex.args[0])
                    if haltOnException:
                        logData(msg)
                        raise

# RS485 master commands thread
def masterCommands(dataFile, outFile):
    global outSeq
    while running:
        for slaveAddr in slaveAddrs:
            with threadLock:
                # grant control of the bus to the slave
                outSeq = sendMsg(dataFile, formatMsg(nextSeq(), masterAddr, int(slaveAddr, 16), PROT_CMD_POLESTAR_MASTER_GRANT), outSeq, outFile)
            # wait for slave to release the bus
            masterEvent.clear()
            masterEvent.wait()
        time.sleep(masterMsgInterval)

# perform the specified commands
def doCommands(dataFile, commands, outFile):
    global inSeq, outSeq
    slaveAddr = int(slaveAddrs[0], 16)
    for command in commands:
        # format the command parameters
        function = int(command[0],16)
        format = "<"+"".join(c[0] for c in command[1:])
        params = [int(p[1:],16) for p in command[1:]]
        # send the command
        outSeq = sendMsg(dataFile, formatMsg(nextSeq(), masterAddr, slaveAddr, function, struct.pack(format, *tuple(params))), outSeq, outFile)
        # wait for the response
        (msg, inSeq) = readMsg(dataFile, inSeq, outFile)
        (msgSeq, fromAddr, toAddr, function, data) = parseMsg(msg)
        msgData = parseData(function, data)
        # wait a bit before sending the next one                    
        time.sleep(commandDelay)

if __name__ == "__main__":
    # initialization
    dataFile = openData(inFileName)
    (outFile, invFile, optFile, jsonFile) = openOutFiles(outFileName, invFileName, optFileName, jsonFileName)
    if passiveMode: # only reading from file or serial device
        # read until eof then terminate
        readData(dataFile, outFile, invFile, optFile, jsonFile)
    else:   # reading and writing to network or serial device
        if commandAction:   # commands were specified
            # perform commands then terminate
            doCommands(dataFile, commands, outFile)
        else:   # network or RS485
            # start a thread for reading
            readThread = threading.Thread(name=readThreadName, target=readData, args=(dataFile, outFile, invFile, optFile, jsonFileName))
            readThread.start()
            debug("debugFiles", "starting", readThreadName)
            if masterMode:  # send RS485 master commands
                # start a thread to poll for data
                masterThread = threading.Thread(name=masterThreadName, target=masterCommands, args=(dataFile, outFile))
                masterThread.start()
                debug("debugFiles", "starting", masterThreadName)
            # wait for termination
            running = waitForEnd()
    # cleanup
    closeData(dataFile)
    closeOutFiles(outFile, invFile, optFile, jsonFile)
    
