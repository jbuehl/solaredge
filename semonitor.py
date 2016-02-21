#!/usr/bin/python

# Monitor SolarEdge inverters using the SolarEdge protocol

# Usage: semonitor [-a] [-b baudrate] [-D delimiter] [-f] [-H] [-i invfile] [-o optfile] 
#                  [-v] inFile [outFile]
# Arguments:
#   inFile           file or serial port to read
#                    If a serial port is specified, monitor the data in real time.
#                    If no file is specified, the program reads from stdin.
#                    If a file is specified, the program processes the data in that file and
#                    terminates, unless the -f option is specified, in which case it waits for 
#                    further data to be written to the file.
# Options:
#   -a               append to output files
#   -b               baud rate for serial input (default: 115200)
#   -D delim         output file delimiter (default: ",")
#   -f               output appended data as the pcap file grows (as in tail -f)
#   -H               write column headers to output files
#   -i invfile       inverter file to write
#   -j jsonfile      json file to write current values to
#   -l               send logging messages to sysout
#   -m               function as a RS485 master
#   -o optfile       optimizer file to write
#   -s inv[,inv,...] slave inverter(s)
#   -v               verbose output
#   -x               halt on exception

# Examples:

import os
import struct
import sys
import time
import getopt
import syslog
import json
import serial
import threading

# debugging
debug = False
debugFiles = False
debugMsgs = False
debugData = False
debugRaw = False

# config defaults
inFileName = ""
outFileName = ""
invFileName = ""
optFileName = ""
jsonFileName = ""
headers = False
delim = ","
writeMode = "w"
following = False
waiting = True
sleepInterval = .1
logSysout = False
lineSize = 16
haltOnException = False
appName = "semonitor"
magic = "\x12\x34\x56\x79"
serialFileName = "/dev/tty"
baudRate = 115200
masterMode = False
masterThreadName = "master"
masterMsgInterval = 1
masterAddr = 0xfffffffe
slaveAddrs = []

# file handles
inFile = None
outFile = None
invFile = None
optFile = None

# file constants
msgHdrLen = 16
devHdrLen = 8
statusLen = 14
checksumLen = 2

# device data dictionaries
invDict = {}
optDict = {}

#def optDictData(seOptData):
#    return {"Date": printDate(seOptData[0]),
#            "Time": printTime(seOptData[0]),
#            "Inverter": convertId(seOptData[1]),
#            "Uptime": "%d" % seOptData[3], # uptime (secs) ?
#            "Vmod": "%f" % seOptData[4], # module voltage
#            "Vopt": "%f" % seOptData[5], # optimizer voltage
#            "Imod": "%f" % seOptData[6], # module current
#            "Eday": "%f" % seOptData[7], # energy produced today (Wh)
#            "Temp": "%f" % seOptData[8] # temperature (C)
#            }

#def invDictData(seInvData):
#    return {"Date": printDate(seInvData[0]),
#            "Time": printTime(seInvData[0]),
#            "Uptime": "%d" % seInvData[1], # uptime (secs) ?
#            "Interval": "%d" % seInvData[2], # time in last interval (secs) ?
#            "Temp": "%f" % seInvData[3], # temperature (C)
#            "Eday": "%f" % seInvData[4], # energy produced today (Wh)
#            "Eac": "%f" % seInvData[5], # energy produced in last interval (Wh)
#            "Vac": "%f" % seInvData[6], # AC volts
#            "Iac": "%f" % seInvData[7], # AC current
#            "Freq": "%f" % seInvData[8], # frequency (Hz)
#            "Vdc": "%f" % seInvData[11], # DC volts
#            "Etot": "%f" % seInvData[13], # total energy produced (Wh)
#            "Pmax": "%f" % seInvData[18], # max power (W) = 5000
#            "Pac": "%f" % seInvData[23] # AC power (W)
#            }
            
# process the input file
def readFile():
    global waiting
    if debugFiles: log("reading", inFileName)
    try:
        # skip to the start of the first message
        readMsg()
        inputSeq = 1
        while waiting:
            msg = readMsg()
            if outFile:
                outFile.write(msg)
                outFile.flush()
            try:
                convertMsg(msg, inputSeq)
            except Exception as ex:
                log("Exception:", ex.args[0])
                logData(msg)
                if haltOnException:
                    raise
            inputSeq += 1
    except KeyboardInterrupt:
        waiting = False
        return    

# return the next message in the file
def readMsg():
    inMsg = ""
    # read 1 byte at a time until the next magic number
    while waiting and (inMsg[-4:] != magic):
        inMsg += readBytes(1)
    return inMsg[:-4]

# return the specified number of bytes from the file
def readBytes(length):
    global waiting
    inBuf = inFile.read(length)
    if inBuf == "":
        if following:
            # wait for data
            while inBuf == "":
                time.sleep(sleepInterval)
                inBuf = inFile.read(length)
        else:   # end of file
            waiting = False
    return inBuf

# hex dump data
def logData(data):
    if data != "":
        printPtr = 0
        while len(data) - printPtr >= lineSize:
            logLine(data[printPtr:printPtr+lineSize])
            printPtr += lineSize
        if printPtr < len(data):
            logLine(data[printPtr:])
def logLine(data):
    log("data:      ", ' '.join(x.encode('hex') for x in data))

# formatted print a message header
def logMsgHdr(inputSeq, msgLen, dataLen, dataLenInv, msgSeq, invFrom, invTo, function):
    log(" ")
    log("message:", inputSeq, "length:", msgLen)
    log("magic:     ", magic.encode('hex'))
    log("dataLen:   ", "%04x" % dataLen)
    log("dataLenInv:", "%04x" % dataLenInv)
    log("sequence:  ", "%04x" % msgSeq)
    log("source:    ", "%08x" % invFrom)
    log("dest:      ", "%08x" % invTo)
    log("function:  ", "%04x" % function)

# formatted print a device
def logDev(devName, seType, seId, devLen, devData):
    log(devName)
    log("    type :", "%04x" % seType)
    log("    id :", "%s" % seId)
    log("    len :", "%04x" % devLen)
    for field in devData.keys():
        log("   ", field, ":", devData[field])

# print a checksum
def logChecksum(checksum):
    log("checksum:  ", "%04x" % checksum)

# parse a message            
def convertMsg(msg, inputSeq):
    # parse the message header
    (dataLen, dataLenInv, msgSeq, invFrom, invTo, function) = struct.unpack("<HHHLLH", msg[0:msgHdrLen])
    if function != 0x0500: return
    if debugRaw: logData(msg)
    if debugData: logMsgHdr(inputSeq, len(msg), dataLen, dataLenInv, msgSeq, invFrom, invTo, function)
    data = msg[msgHdrLen:-checksumLen]
    # validate the message
    if dataLen != ~dataLenInv & 0xffff:
        raise Exception("Length error")
    checksum = struct.unpack("<H", msg[-checksumLen:])[0]
    calcsum = calcCrc(struct.pack(">HLLH", msgSeq, invFrom, invTo, function)+data)
    if calcsum != checksum:
        raise Exception("Checksum error. Expected 0x%04x, got 0x%04x" % (checksum, calcsum))
    # parse the data
    if dataLen > 0:
        if function == 0x0500:
            convertDevice(data)
            if masterMode: sendMsg(msgSeq, invFrom, invTo, 0x0080)
            writeJson()
        elif function == 0x039f:
            convertStatus(data)
        else:   # unknown function type
            raise Exception("Unknown function 0x%04x" % function)
    if debugData:
        logChecksum(checksum)

# send a message
def sendMsg(msgSeq, fromAddr, toAddr, function, data=""):
    checksum = calcCrc(struct.pack(">HLLH", msgSeq, invTo, invFrom, function))
    msg = magic + struct.pack("<HHHLLHH", len(data), ~len(data) & 0xffff, msgSeq, invTo, invFrom, function) + data + struct.pack("<H", checksum)
    if debugData: 
        log("sending")
        logMsgHdr(msgSeq, len(msg), len(data), ~len(data) & 0xffff, msgSeq, invTo, invFrom, function)
        logData(data)
        logChecksum(checksum)
    inFile.write(msg)

# parse status data
def convertStatus(msg):
#    status = struct.unpack("<HHHHHHH", msg)
#    if debugData: log("status", "%d "*len(status) % status)
    if debugData: logData(msg)
    return statusLen

# parse device data
def convertDevice(devData):
    global invDict, optDict
    dataPtr = 0
    while dataPtr < len(devData):
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", devData[dataPtr:dataPtr+devHdrLen])
        seId = convertId(seId)
        dataPtr += devHdrLen
        # device data
        if seType == 0x0000:    # optimizer log data
            optDict[seId] = convertOptData(seId, optItems, devData[dataPtr:dataPtr+devLen])
            if debugData: logDev("optimizer:     ", seType, seId, devLen, optDict[seId])
            writeData(optFile, optOutFmt, optDict[seId], optItems)
        elif seType == 0x0080:  # new format optimizer log data
            optDict[seId] = convertNewOptData(seId, optItems, devData[dataPtr:dataPtr+devLen])
            if debugData: logDev("optimizer:     ", seType, seId, devLen, optDict[seId])
            writeData(optFile, optOutFmt, optDict[seId], optItems)
        elif seType == 0x0010:  # inverter log data
            invDict[seId] = convertInvData(seId, invItems, devData[dataPtr:dataPtr+devLen])
            if debugData: logDev("inverter:     ", seType, seId, devLen, invDict[seId])
            writeData(invFile, invOutFmt, invDict[seId], invItems)
        else:   # unknown device type
            raise Exception("Unknown device 0x%04x" % seType) 
        dataPtr += devLen

# inverter data interpretation
#
#   timeStamp = seData[0]
#   Uptime = seData[1] # uptime (secs) ?
#   Interval = seData[2] # time in last interval (secs) ?
#   Temp = seData[3] # temperature (C)
#   Eday = seData[4] # energy produced today (Wh)
#   Eac = seData[5] # energy produced in last interval (Wh)
#   Vac = seData[6] # AC volts
#   Iac = seData[7] # AC current
#   freq = seData[8] # frequency (Hz)
#   data9 = seData[9] # 0xff7fffff
#   data10 = seData[10] # 0xff7fffff
#   Vdc = seData[11] # DC volts
#   data12 = seData[12] # 0xff7fffff
#   Etot = seData[13] # total energy produced (Wh)
#   data14 = seData[14] # ?
#   data15 = seData[15] # 0xff7fffff
#   data16 = seData[16] # 0.0
#   data17 = seData[17] # 0.0
#   Pmax = seData[18] # max power (W) = 5000
#   data19 = seData[19] # 0.0
#   data20 = seData[20] # ?
#   data21 = seData[21] # 0xff7fffff
#   data22 = seData[22] # 0xff7fffff
#   Pac = seData[23] # AC power (W)
#   data24 = seData[24] # ?
#   data25 = seData[25] # 0xff7fffff
    
# input file format strings
invInFmt = "<LLLffffffLLfLffLfffffLLffL"
# input tuple mappings
invIdx = [0,1,2,3,4,5,6,7,8,11,13,18,23]
# device data item names
invItems = ["Date", "Time", "ID", "Uptime", "Interval", "Temp", "Eday", "Eac", "Vac", "Iac", "Freq", "Vdc", "Etot", "Pmax", "Pac"]

def convertInvData(seId, invItems, devData):
    # unpack data and map to items
    seInvData = [struct.unpack(invInFmt, devData)[i] for i in invIdx]
    return devDataDict(seId, invItems, seInvData)

# optimizer data interpretation
#
#   timeStamp = seData[0]
#   inverter = seData[1] & 0xff7fffff
#   Uptime = seData[3] # uptime (secs) ?
#   Vmod = seData[4] # module voltage
#   Vopt = seData[5] # optimizer voltage
#   Imod = seData[6] # module current
#   Eday = seData[7] # energy produced today (Wh)
#   Temp = seData[8] # temperature (C)

# input file format strings
optInFmt = "<LLLLfffff"
# input tuple mappings
optIdx = [0,1,3,4,5,6,7,8]
# device data item names
optItems = ["Date", "Time", "ID", "Inverter", "Uptime", "Vmod", "Vopt", "Imod", "Eday", "Temp"]

def convertOptData(seId, optItems, devData):
    # unpack data and map to items
    seOptData = [struct.unpack(optInFmt, devData)[i] for i in optIdx]
    seOptData[1] = convertId(seOptData[1])
    return devDataDict(seId, optItems, seOptData)

# Decode optimiser data in packet type 0x0080
#  (into same order as original data)
#
# Byte index (in reverse order):
# 
# 0c 0b 0a 09 08 07 06 05 04 03 02 01 00
# Tt Ee ee Cc cO o# pp Uu uu Dd dd dd dd 
#  # = oo|Pp
#
#  Temp, 8bit (1.6 degC)  Signed?, 1.6 is best guess at factor
#  Energy in day, 16bit (1/4 Wh)
#  Current (panel), 12 bit (1/160 Amp)
#  voltage Output, 10 bit (1/8 v)
#  voltage Panel, 10 bit (1/8 v)
#  Uptime of optimiser, 16 bit (secs)
#  DateTime, 32 bit (secs)
#
def convertNewOptData(seId, optItems, devData):
    data = bytearray()
    data.extend(devData)
    (timeStamp, uptime) = struct.unpack("<LH", devData[0:6])
    vpan = 0.125 * (data[6] | (data[7] <<8 & 0x300))
    vopt = 0.125 * (data[7] >>2 | (data[8] <<6 & 0x3c0))
    imod = 0.00625 * (data[9] <<4 | (data[8] >>4 & 0xf))
    eday = 0.25 * (data[11] <<8 | data[10])
    temp = 1.6 * struct.unpack("<b", devData[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return devDataDict(seId, optItems, [timeStamp, 0, 0, uptime, vpan, vopt, imod, eday, temp])

# create a dictionary of device data items
def devDataDict(seId, itemNames, itemValues):
    devDict = {}
    devDict["Date"] = printDate(itemValues[0])
    devDict["Time"] = printTime(itemValues[0])
    devDict["ID"] = seId
    for i in range(3, len(itemNames)):
        devDict[itemNames[i]] = itemValues[i-2]
    return devDict
    
# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# write device data to json file
def writeJson():
    if jsonFileName != "":
        if debugMsgs: log("writing", jsonFileName)
        json.dump({"inverters": invDict, "optimizers": optDict}, open(jsonFileName, "w"))
    
# write device data to output file
# device data output file format strings
invOutFmt = ["%s", "%s", "%s", "%d", "%d", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f"]
optOutFmt = ["%s", "%s", "%s", "%s", "%d", "%f", "%f", "%f", "%f", "%f"]
def writeData(outFile, outFmt, devDict, devItems):
    if outFile:
        outMsg = delim.join([(outFmt[i] % devDict[devItems[i]]) for i in range(len(devItems))])
        try:
            if debugMsgs: log("writing", outMsg)
            outFile.write(outMsg+"\n")
            outFile.flush()
        except:
            terminate(1, "Error writing output file "+outFile.name)

# create output data tuple
#def outData(seId, seData, seIdx):
#    outList = [printDate(seData[0]), printTime(seData[0]), seId]
#    for idx in seIdx:
#        outList += [seData[idx]]
#    return tuple(outList)
                
# format a date        
def printDate(timeStamp):
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

# format a time       
def printTime(timeStamp):
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))

# crc calculation
#
# CRC-16 with the following parameters:
#
# width=16 poly=0x8005 init=0x5a5a refin=true refout=true xorout=0x0000

crcTable = [
0x0000,  0xc0c1,  0xc181,  0x0140,  0xc301,  0x03c0,  0x0280,  0xc241, 
0xc601,  0x06c0,  0x0780,  0xc741,  0x0500,  0xc5c1,  0xc481,  0x0440, 
0xcc01,  0x0cc0,  0x0d80,  0xcd41,  0x0f00,  0xcfc1,  0xce81,  0x0e40, 
0x0a00,  0xcac1,  0xcb81,  0x0b40,  0xc901,  0x09c0,  0x0880,  0xc841, 
0xd801,  0x18c0,  0x1980,  0xd941,  0x1b00,  0xdbc1,  0xda81,  0x1a40, 
0x1e00,  0xdec1,  0xdf81,  0x1f40,  0xdd01,  0x1dc0,  0x1c80,  0xdc41, 
0x1400,  0xd4c1,  0xd581,  0x1540,  0xd701,  0x17c0,  0x1680,  0xd641, 
0xd201,  0x12c0,  0x1380,  0xd341,  0x1100,  0xd1c1,  0xd081,  0x1040, 
0xf001,  0x30c0,  0x3180,  0xf141,  0x3300,  0xf3c1,  0xf281,  0x3240, 
0x3600,  0xf6c1,  0xf781,  0x3740,  0xf501,  0x35c0,  0x3480,  0xf441, 
0x3c00,  0xfcc1,  0xfd81,  0x3d40,  0xff01,  0x3fc0,  0x3e80,  0xfe41, 
0xfa01,  0x3ac0,  0x3b80,  0xfb41,  0x3900,  0xf9c1,  0xf881,  0x3840, 
0x2800,  0xe8c1,  0xe981,  0x2940,  0xeb01,  0x2bc0,  0x2a80,  0xea41, 
0xee01,  0x2ec0,  0x2f80,  0xef41,  0x2d00,  0xedc1,  0xec81,  0x2c40, 
0xe401,  0x24c0,  0x2580,  0xe541,  0x2700,  0xe7c1,  0xe681,  0x2640, 
0x2200,  0xe2c1,  0xe381,  0x2340,  0xe101,  0x21c0,  0x2080,  0xe041, 
0xa001,  0x60c0,  0x6180,  0xa141,  0x6300,  0xa3c1,  0xa281,  0x6240, 
0x6600,  0xa6c1,  0xa781,  0x6740,  0xa501,  0x65c0,  0x6480,  0xa441, 
0x6c00,  0xacc1,  0xad81,  0x6d40,  0xaf01,  0x6fc0,  0x6e80,  0xae41, 
0xaa01,  0x6ac0,  0x6b80,  0xab41,  0x6900,  0xa9c1,  0xa881,  0x6840, 
0x7800,  0xb8c1,  0xb981,  0x7940,  0xbb01,  0x7bc0,  0x7a80,  0xba41, 
0xbe01,  0x7ec0,  0x7f80,  0xbf41,  0x7d00,  0xbdc1,  0xbc81,  0x7c40, 
0xb401,  0x74c0,  0x7580,  0xb541,  0x7700,  0xb7c1,  0xb681,  0x7640, 
0x7200,  0xb2c1,  0xb381,  0x7340,  0xb101,  0x71c0,  0x7080,  0xb041, 
0x5000,  0x90c1,  0x9181,  0x5140,  0x9301,  0x53c0,  0x5280,  0x9241, 
0x9601,  0x56c0,  0x5780,  0x9741,  0x5500,  0x95c1,  0x9481,  0x5440, 
0x9c01,  0x5cc0,  0x5d80,  0x9d41,  0x5f00,  0x9fc1,  0x9e81,  0x5e40, 
0x5a00,  0x9ac1,  0x9b81,  0x5b40,  0x9901,  0x59c0,  0x5880,  0x9841, 
0x8801,  0x48c0,  0x4980,  0x8941,  0x4b00,  0x8bc1,  0x8a81,  0x4a40, 
0x4e00,  0x8ec1,  0x8f81,  0x4f40,  0x8d01,  0x4dc0,  0x4c80,  0x8c41, 
0x4400,  0x84c1,  0x8581,  0x4540,  0x8701,  0x47c0,  0x4680,  0x8641, 
0x8201,  0x42c0,  0x4380,  0x8341,  0x4100,  0x81c1,  0x8081,  0x4040]

def calcCrc(data):
    crc = 0x5a5a    # initial value
    for d in data:
         crc = crcTable[(crc ^ ord(d)) & 0xff] ^ (crc >> 8)
    return crc

# get command line options and arguments
def getOpts():
    global debug, debugFiles, debugMsgs, debugData, debugRaw
    global writeMode, delim, following, headers, masterMode, baudRate
    global outFileName, invFileName, optFileName, jsonFileName, slaveAddrs
    global pcapDir, inFileName, inFiles, logSysout, haltOnException
    (opts, args) = getopt.getopt(sys.argv[1:], "ab:D:fp:Hi:j:lmo:s:vx")
    try:
        inFileName = args[0]
    except:
        inFileName = "stdin"      
    try:
        outFileName = args[1]
    except:
        pass
    for opt in opts:
        if opt[0] == "-a":
            writeMode = "a"
        elif opt[0] == "-b":
            baudRate = opt[1] 
        elif opt[0] == "-D":
            delim = opt[1] 
        elif opt[0] == "-f":
            following = True
        elif opt[0] == "-H":
            headers = True
        elif opt[0] == "-i":
            invFileName = opt[1]
        elif opt[0] == "-j":
            jsonFileName = opt[1]
        elif opt[0] == "-l":
            logSysout = True
        elif opt[0] == "-m":
            masterMode = True
        elif opt[0] == "-o":
            optFileName = opt[1]
        elif opt[0] == "-s":
            slaveAddrs = opt[1].split(",")
        elif opt[0] == "-v":
            if not debug:
                debug = True        # -v
                debugFiles = True
            elif not debugMsgs:
                debugMsgs = True    # -vv
            elif not debugData:
                debugData = True    # -vvv
            elif not debugRaw:
                debugRaw = True    # -vvvv
        elif opt[0] == "-x":
            haltOnException = True
    if debug:
        log("debug:", debug)  
        log("debugFiles:", debugFiles)  
        log("debugMsgs:", debugMsgs)
        log("debugData:", debugData)
        log("debugRaw:", debugRaw)
        log("headers:", headers)
        log("delim:", delim)
        log("append:", writeMode)
        log("baudRate:", baudRate)
        log("following:", following)
        log("inFileName:", inFileName)
        log("outFileName:", outFileName)
        log("invFileName:", invFileName)
        log("optFileName:", optFileName)
        log("jsonFileName:", jsonFileName)
        log("logSysout:", logSysout)
        log("masterMode:", masterMode)
        log("slaveAddrs:", slaveAddrs)
        log("haltOnException:", haltOnException)

# open the output files if they are specified
def openOutFiles():
    global outFile, invFile, optFile
    if outFileName != "":
        try:
            if debugFiles: log("writing", outFileName)
            outFile = open(outFileName, writeMode)
        except:
            terminate(1, "Unable to open "+outFileName)
    if invFileName != "":
        try:
            if debugFiles: log("writing", invFileName)
            invFile = open(invFileName, writeMode)
            if headers: writeHeaders(invFile, invItems, delim)
        except:
            terminate(1, "Unable to open "+invFileName)
    if optFileName != "":
        try:
            if debugFiles: log("writing", optFileName)
            optFile = open(optFileName, writeMode)
            if headers: writeHeaders(optFile, optItems, delim)
        except:
            terminate(1, "Unable to open "+optFileName)
    if jsonFileName != "":
        if debugFiles: log("writing", jsonFileName)

# write output file headers
def writeHeaders(outFile, items, delim):
    outFile.write(delim.join(item for item in items)+"\n")

# open the specified input file
def openInFile():
    global inFile, following
    if debugFiles: log("opening", inFileName)
    if inFileName == "stdin":
        inFile = sys.stdin
        following = True
    elif inFileName[0:len(serialFileName)] == serialFileName:
        inFile = serial.Serial(inFileName, baudrate=baudRate)
        following = True
    else:
        try:
            inFile = open(inFileName)
            if masterMode:
                terminate(1, "Master mode not allowed with file input")
        except:
            terminate(1, "Unable to open "+inFileName)

# start a thread to send RS485 master messages
def startMaster():
    if masterMode:
        masterThread = threading.Thread(name=masterThreadName, target=sendMasterMsg)
        masterThread.start()
        if debugFiles: log("starting", masterThreadName)
        
# master message thread
def sendMasterMsg():
    msgSeq = 0
    function = 0x0302
    while waiting:
        msgSeq += 1
        for slaveAddr in slaveAddrs:
            sendMsg(msgSeq, masterAddr, slaveAddr, 0x0302)
        time.sleep(masterMsgInterval)
        
# close all files        
def closeFiles():
    if inFile: inFile.close()
    if outFile: outFile.close()
    if invFile: invFile.close()
    if optFile: optFile.close()

# log a message
def log(*args):
    message = args[0]+" "
    for arg in args[1:]:
        message += arg.__str__()+" "
    if logSysout:
        print time.asctime(time.localtime())+" "+message
    else:
        syslog.syslog(appName+" "+message)

# program termination
def terminate(code=0, msg=""):
    log(msg)
    sys.exit(code)
    
if __name__ == "__main__":
    getOpts()         
    openInFile()
    openOutFiles()
    startMaster()
    readFile()
    closeFiles()
