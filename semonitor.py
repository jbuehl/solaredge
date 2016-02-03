#!/usr/bin/python

# Monitor SolarEdge inverters using the SolarEdge protocol on the RS485 interface

# Usage: semonitor [-a] [-b baudrate] [-D delimiter] [-f] [-H] [-i invfile] [-o optfile] 
#                  [-v] inFile [outFile]
# Arguments:
#   inFile          file or serial port to read
#                   If a serial port is specified, monitor the data in real time.
#                   If no file is specified, the program reads from stdin.
#                   If a file is specified, the program processes the data in that file and
#                   terminates, unless the -f option is specified, in which case it waits for 
#                   further data to be written to the file.
# Options:
#   -a              append to output files
#   -b              baud rate for serial input (default: 115200)
#   -D delim        output file delimiter (default: ",")
#   -f              output appended data as the pcap file grows (as in tail -f)
#   -H              write column headers to output files
#   -i invfile      inverter file to write
#   -j jsonfile     json file to write current values to
#   -l              send logging messages to sysout
#   -m              function as a RS485 master
#   -o optfile      optimizer file to write
#   -v              verbose output

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
#Simport crc16

# configuration
debug = False
debugFiles = False
debugRecs = False
debugData = False
debugRaw = False
debugSeq = []
inFileName = ""
inputSeq = 0
outFileName = ""
invFileName = ""
optFileName = ""
jsonFileName = ""
headers = False
delim = ","
writeMode = "w"
masterMode = False
sleepInterval = 10
dbRetryInterval = 60
logSysout = False
lineSize = 16
appName = "semonitor"
serialIn = False
baudRate = 115200
masterThreadName = "master"
masterMsgInterval = 1
waiting = True
ignore = [0x0302, 0x0347, 0x039a, 0x039f]

# file handles
inFile = None
outFile = None
invFile = None
optFile = None
jsonFile = None

# file constants
seHdrLen = 20
seDevHdrLen = 8

# device data dictionaries
invDict = {}
optDict = {}

# input file format strings
invInFmt = "<LLLffffffLLfLffLfffffLLffL"
optInFmt = "<LLLLfffff"
# input tuple mappings
invIdx = [1,2,3,4,5,6,7,8,11,13,18,23]
optIdx = [2,3,4,5,6,7,8]
# output file headers
invHdr = "Date,Time,ID,Uptime,Intrvl,Temp,Eday,Eint,Vac,Iac,Freq,Vdc,Etot,Pmax,Pac"
optHdr = "Date,Time,ID,Inv,Uptime,Vmod,Vopt,Imod,Eday,Temp"
# output file format strings
invOutFmt = "%s,%s,%s,%d,%d,%f,%f,%f,%f,%f,%f,%f,%f,%f,%f"
optOutFmt = "%s,%s,%s,%s,%d,%f,%f,%f,%f,%f"

# inverter record data interpretation
# this class is included for documentation purposes only
class invData:
    def __init__(self, seInvData):
        self.id = seId
        self.timeStamp = seInvData[0]
        self.Uptime = seInvData[1] # uptime (secs) ?
        self.Interval = seInvData[2] # time in last interval (secs) ?
        self.Temp = seInvData[3] # temperature (C)
        self.Eday = seInvData[4] # energy produced today (Wh)
        self.Eac = seInvData[5] # energy produced in last interval (Wh)
        self.Vac = seInvData[6] # AC volts
        self.Iac = seInvData[7] # AC current
        self.freq = seInvData[8] # frequency (Hz)
        self.data9 = seInvData[9] # 0xff7fffff
        self.data10 = seInvData[10] # 0xff7fffff
        self.Vdc = seInvData[11] # DC volts
        self.data12 = seInvData[12] # 0xff7fffff
        self.Etot = seInvData[13] # total energy produced (Wh)
        self.data14 = seInvData[14] # ?
        self.data15 = seInvData[15] # 0xff7fffff
        self.data16 = seInvData[16] # 0.0
        self.data17 = seInvData[17] # 0.0
        self.Pmax = seInvData[18] # max power (W) = 5000
        self.data19 = seInvData[19] # 0.0
        self.data20 = seInvData[20] # ?
        self.data21 = seInvData[21] # 0xff7fffff
        self.data22 = seInvData[22] # 0xff7fffff
        self.Pac = seInvData[23] # AC power (W)
        self.data24 = seInvData[24] # ?
        self.data25 = seInvData[25] # 0xff7fffff
    
# optimizer record data interpretation
# this class is included for documentation purposes only
class optData:
    def __init__(self, seId, seOptData):
        self.id = seId
        self.timeStamp = seOptData[0]
        self.inverter = seOptData[1] & 0xff7fffff
        self.Uptime = seOptData[3] # uptime (secs) ?
        self.Vmod = seOptData[4] # module voltage
        self.Vopt = seOptData[5] # optimizer voltage
        self.Imod = seOptData[6] # module current
        self.Eday = seOptData[7] # energy produced today (Wh)
        self.Temp = seOptData[8] # temperature (C)

def optDictData(seOptData):
    return {"Date": printDate(seOptData[0]),
            "Time": printTime(seOptData[0]),
            "Inverter": convertId(seOptData[1]),
            "Uptime": "%d" % seOptData[3], # uptime (secs) ?
            "Vmod": "%f" % seOptData[4], # module voltage
            "Vopt": "%f" % seOptData[5], # optimizer voltage
            "Imod": "%f" % seOptData[6], # module current
            "Eday": "%f" % seOptData[7], # energy produced today (Wh)
            "Temp": "%f" % seOptData[8] # temperature (C)
            }

def invDictData(seInvData):
    return {"Date": printDate(seInvData[0]),
            "Time": printTime(seInvData[0]),
            "Uptime": "%d" % seInvData[1], # uptime (secs) ?
            "Interval": "%d" % seInvData[2], # time in last interval (secs) ?
            "Temp": "%f" % seInvData[3], # temperature (C)
            "Eday": "%f" % seInvData[4], # energy produced today (Wh)
            "Eac": "%f" % seInvData[5], # energy produced in last interval (Wh)
            "Vac": "%f" % seInvData[6], # AC volts
            "Iac": "%f" % seInvData[7], # AC current
            "Freq": "%f" % seInvData[8], # frequency (Hz)
            "Vdc": "%f" % seInvData[11], # DC volts
            "Etot": "%f" % seInvData[13], # total energy produced (Wh)
            "Pmax": "%f" % seInvData[18], # max power (W) = 5000
            "Pac": "%f" % seInvData[23] # AC power (W)
            }

def readFile():
    global waiting
    # skip to the start of the first record
    readRec()
    inputSeq = 1
    while True:
        rec = readRec()
#        waiting = False
        if True: #len(rec) > 100:
            try:
                convertRec(rec, inputSeq)
            except:
                log("exception***")
                dumpRec(rec)
        inputSeq += 1

# return the next record in the file
def readRec():
    inRec = ""
    # read 1 byte at a time until the next magic number
    while inRec[-4:] != "\x12\x34\x56\x79":
        inRec += readBytes(1)
    return "\x12\x34\x56\x79" + inRec[:-4]

# return the specified number of bytes from the file
def readBytes(length):
    inBuf = None
    inBuf = inFile.read(length)
    # wait for data
    while inBuf == None:
        time.sleep(sleepInterval)
        inBuf = inFile.read(length)
    if outFile:
        outFile.write(inBuf)
        outFile.flush()
    return inBuf

# hex dump the specified record
def dumpRec(rec):
    printPtr = 0
    while len(rec) - printPtr >= lineSize:
        dumpLine(rec[printPtr:printPtr+lineSize])
        printPtr += lineSize
    if printPtr < len(rec):
        dumpLine(rec[printPtr:])

# hex dump a line of data
def dumpLine(rec):
    log("rawdata:", ' '.join(x.encode('hex') for x in rec))

# formatted print a record header
def printRecHdr(seDataLen, ffff, msgSeq, invFrom, invTo, function):
    log("dataLen:  ", "%04x" % seDataLen)
    log("flags:    ", "%04x" % ffff)
    log("sequence: ", "%04x" % msgSeq)
    log("source:   ", "%08x" % invFrom)
    log("dest:     ", "%08x" % invTo)
    log("function: ", "%04x" % function)

# formatted print a device header
def printDevHdr(seType, seId, seDeviceLen):
    log("    type:     ", "%04x" % seType)
    log("    id:       ", "%08x" % seId)
    log("    len:      ", "%04x" % seDeviceLen)

# formatted print device data
def printDevice(devData):
    for field in devData.keys():
        log("   ", field, ":", devData[field])

# convert a data record            
def convertRec(rec, inputSeq):
    global waiting
    # record header
    (magic) = struct.unpack(">L", rec[0:4])
    (seDataLen, ffff, msgSeq, invFrom, invTo, function) = struct.unpack("<HHHLLH", rec[4:20])
#    if function in ignore:
#        return
#    if inputSeq not in range(35350, 35359):
#        return
#    if inputSeq > 100:
#        sys.exit(0)
    if debugRecs: log(" ")
    if debugRaw: dumpRec(rec)
    if debugData: log("record:", inputSeq, "length:", len(rec))
    if debugData: log("magic:    ", "%08x" % magic)
    if debugData: printRecHdr(seDataLen, ffff, msgSeq, invFrom, invTo, function)
    dataPtr = 20
    while dataPtr < len(rec)-4:
        if function == 0x0500:
            # device header
            (seType, seId, seDeviceLen) = struct.unpack("<HLH", rec[dataPtr:dataPtr+seDevHdrLen])
            dataPtr += seDevHdrLen
            # device data
            if seType == 0x0000:    # optimizer log data
                if debugData: log("optimizer:     ")
                if debugData: printDevHdr(seType, seId, seDeviceLen)
                seOptData = list(struct.unpack(optInFmt, rec[dataPtr:dataPtr+seDeviceLen]))
    #            seOptData[2] = convertId(seOptData[2])
                optDict[seId] = optDictData(seOptData)
                if debugData: printDevice(optDict[seId])
                writeJson()
                writeData(seId, seOptData, optIdx, optOutFmt, optFile)
    #        elif seType == 0x0080:  # new format optimizer log data
    #            seData = readBytes(seDeviceLen)
    #            seOptData = convertNewOptData(seData)
    #            optDict[seId] = optDictData(seOptData)
    #            writeJson()
    #            writeData(seId, seOptData, optIdx, optOutFmt, optFile)
            elif seType == 0x0010:  # inverter log data
                if debugData: log("inverter:     ")
                if debugData: printDevHdr(seType, seId, seDeviceLen)
                seInvData = list(struct.unpack(invInFmt, rec[dataPtr:dataPtr+seDeviceLen]))
                invDict[seId] = invDictData(seInvData)
                if debugData: printDevice(invDict[seId])
                writeJson()
                writeData(seId, seInvData, invIdx, invOutFmt, invFile)
            else:   # unknown device type
                if debugData: log("unknown:     ")
                dumpRec(rec[dataPtr:dataPtr+seDeviceLen])
            dataPtr += seDeviceLen
        else:
            dumpRec(rec[dataPtr:-2])
            dataPtr = len(rec)-2
    if debugData: log("checksum: ", "%04x" % struct.unpack("<H", rec[-2:]))
#    checkRec = rec[4:-2]
#    if debugData: log("mod16:    ", "%04x" % checksum16(checkRec))
#    if debugData: log("CRC16:    ", "%04x" % crc16.crc16xmodem(checkRec))
#    if debugData: log("IP:       ", "%04x" % IPChecksum(checkRec))
#    if debugData: log("fletcher: ", "%04x" % fletcher(checkRec))
#    if debugData: log("BSD:      ", "%04x" % bsdChecksum(checkRec))
    if debugData: log(" ")

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
def convertNewOptData(seData):
    data = bytearray()
    data.extend(seData)
    (timeStamp, uptime) = struct.unpack("<LH", seData[0:6])
    vpan = 0.125 * (data[6] | (data[7] <<8 & 0x300))
    vopt = 0.125 * (data[7] >>2 | (data[8] <<6 & 0x3c0))
    imod = 0.00625 * (data[9] <<4 | (data[8] >>4 & 0xf))
    eday = 0.25 * (data[11] <<8 | data[10])
    temp = 1.6 * struct.unpack("<b", seData[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return [timeStamp, 0, 0, uptime, vpan, vopt, imod, eday, temp]

# compute BSD checksum
def bsdChecksum(msg):
    checksum = 0
    for ch in msg:
        checksum = (checksum >> 1) + ((checksum & 1) << 15)
        checksum += ord(ch)
        checksum &= 0xffff;
    return checksum

# compute IP checksum
def IPChecksum(msg):
    s = 0
    for i in range(0, len(msg), 2):
        w = ord(msg[i]) + (ord(msg[i+1]) << 8)
        s = carry_around_add(s, w)
    return ~s & 0xffff

def carry_around_add(a, b):
    c = a + b
    return (c & 0xffff) + (c >> 16)

# compute Fletcher checksum
def fletcher(msg):
    sum1 = 0
    sum2 = 0
    for i in range(len(msg)):
        sum1 = ( sum1 + ord(msg[i]) ) % 255
        sum2 = ( sum2 + sum1       ) % 255
    check1 = 255 - (( sum1 + sum2    ) % 255)
    check2 = 255 - (( sum1 + check1 ) % 255)
    return (check1 << 8) + check2
    
# Compute the 16 bit checksum of a string of bytes               
def checksum16(msg):
    return reduce(lambda x,y:x+y, map(ord, msg)) % 16384

# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# write device data to json file
def writeJson():
    if jsonFileName != "":
        if debugRecs: log("writing", jsonFileName)
        json.dump({"inverters": invDict, "optimizers": optDict}, open(jsonFileName, "w"))
    
# write device data
def writeData(seId, seData, seIdx, outFmt, outFile):
    if outFile:
        outRec = outFmt % outData(seId, seData, seIdx)
        try:
            if debugRecs: log("writing", outRec)
            outFile.write(outRec+"\n")
            outFile.flush()
        except:
            terminate(1, "Error writing output file "+outFile.name)

# create output data tuple
def outData(seId, seData, seIdx):
    outList = [printDate(seData[0]), printTime(seData[0]), seId]
    for idx in seIdx:
        outList += [seData[idx]]
    return tuple(outList)
                
# format a date        
def printDate(timeStamp):
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

# format a time       
def printTime(timeStamp):
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))

# get command line options and arguments
def getOpts():
    global debug, debugFiles, debugRecs, debugData, debugRaw
    global writeMode, delim, follow, headers, masterMode, baudRate
    global outFileName, invFileName, optFileName, jsonFileName
    global pcapDir, inFileName, inFiles, logSysout
    (opts, args) = getopt.getopt(sys.argv[1:], "ab:D:fp:Hi:j:lmo:v")
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
            follow = True
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
        elif opt[0] == "-v":
            if not debug:
                debug = True        # -v
                debugFiles = True
            elif not debugRecs:
                debugRecs = True    # -vv
            elif not debugData:
                debugData = True    # -vvv
            elif not debugRaw:
                debugRaw = True    # -vvvv
    if debug:
        log("debug:", debug)  
        log("debugFiles:", debugFiles)  
        log("debugData:", debugData)
        log("headers:", headers)
        log("delim:", delim)
        log("append:", writeMode)
        log("baudRate:", baudRate)
        log("inFileName:", inFileName)
        log("outFileName:", outFileName)
        log("invFileName:", invFileName)
        log("optFileName:", optFileName)
        log("jsonFileName:", jsonFileName)
        log("logSysout:", logSysout)
        log("masterMode:", masterMode)

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
            if headers: invFile.write(invHdr+"\n")
        except:
            terminate(1, "Unable to open "+invFileName)
    if optFileName != "":
        try:
            if debugFiles: log("writing", optFileName)
            optFile = open(optFileName, writeMode)
            if headers: optFile.write(optHdr+"\n")
        except:
            terminate(1, "Unable to open "+optFileName)
    if jsonFileName != "":
        if debugFiles: log("writing", jsonFileName)

# open the specified input file
def openInFile(inFileName):
    global inFile, inputSeq, serialIn
    if inFileName == "stdin":
        inFile = sys.stdin
    elif inFileName[0:8] == "/dev/tty":
        serialIn = True
        inFile = serial.Serial(inFileName, baudrate=baudRate)
    else:
        try:
            if debugFiles: log("opening", inFileName)
            inFile = open(inFileName)
            inputSeq = 0
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
#    msg = "\x12\x34\x56\x79\x00\x00\xff\xff\x9c\x6e\x20\x49\x10\x7f\x16\x4a\x10\x7f\x02\x03\xf5\xa6"
    chksum = 0x3bbb
    while waiting:
        msg = struct.pack("<LHHHLLHH", 0x79563412, 0x0000, 0xffff, 0x0000, 0x7f100000, 0x7f104a16, 0x0302, chksum)
        if debugData: 
            log(masterThreadName, "sending")
            dumpRec(msg)
            log(" ")
        inFile.write(msg)
        time.sleep(masterMsgInterval)
        
# master message thread
#def sendMasterMsg():
##    msg = "\x12\x34\x56\x79\x00\x00\xff\xff\x9c\x6e\x20\x49\x10\x7f\x16\x4a\x10\x7f\x02\x03\xf5\xa6"
#    chksum = 0x3bb0
#    masterMsgInterval = 1
#    while waiting:
#        msg = struct.pack("<LHHHLLHH", 0x79563412, 0x0000, 0xffff, 0x0000, 0x7f100000, 0x7f104a16, 0x0302, chksum)
#        if chksum % 0x0100 == 0:
#            log("trying", "0x%04x"%chksum)
#        if debugData: 
#            log(masterThreadName, "sending")
#            dumpRec(msg)
#            log(" ")
#        inFile.write(msg)
#        time.sleep(masterMsgInterval)
#        chksum += 1
#    log("match", "0x%04x"%chksum)
        
# close all files        
def closeFiles():
    if inFile: inFile.close()
    if outFile: outFile.close()
    if invFile: invFile.close()
    if optFile: optFile.close()

# set delimiters for output files
def setFileDelims():
    global invHdr, optHdr, invSqlFmt, invOutFmt, optSqlFmt, optOutFmt
    invHdr = invHdr.replace(",", delim)
    optHdr = optHdr.replace(",", delim)
    invOutFmt = invOutFmt.replace(",", delim)
    optOutFmt = optOutFmt.replace(",", delim)

def log(*args):
    message = args[0]+" "
    for arg in args[1:]:
        message += arg.__str__()+" "
    if logSysout:
        print time.asctime(time.localtime())+" "+message
    else:
        syslog.syslog(appName+" "+message)

def terminate(code, msg=""):
    print msg
    sys.exit(code)
    
if __name__ == "__main__":
    getOpts()         
    # open output
    setFileDelims()
    openOutFiles()
    # process the input file
    if debugFiles: log("reading", inFileName)
    openInFile(inFileName)
    openOutFiles()
    try:
        startMaster()
        readFile()
    except KeyboardInterrupt:
        waiting = False
        closeFiles()
