#!/usr/bin/python

# Read a file that is a capture of the TCP stream from a SolarEdge inverter to the SE server.
# Filter out and parse the log data for inverters and optimizers.

# The output can be specified in various modes:
# 1. batch - output is written to csv files
# 2. realtime - output is loaded into a database

# Usage: seconvert3 [-a] [-d database] [-f] [-H] [-h hostname] [-i invfile] [-o optfile] 
#                  [-p passwd] [-u username] [-v] inFile
# Arguments:
#   inFile          file to read
#                   If no file is specified, the program reads from stdin.
#                   If a file is specified, the program processes the data in that file and
#                   terminates, unless the -f option is specified, in which case it waits for 
#                   further data to be written to the pcap file.
# Options:
#   -a              append to output files
#   -D delim        output file delimiter (default: ",")
#   -f              output appended data as the pcap file grows (as in tail -f)
#   -H              write column headers to output files
#   -h hostname     database hostname or IP address
#   -i invfile      inverter file to write
#   -j jsonfile     json file to write current values to
#   -l              send logging messages to sysout
#   -o optfile      optimizer file to write
#   -v              verbose output

# Examples:
#   seconvert2 -H pcap-20140122000001.pcap
#
#   Convert the data in file pcap-20140122000001.pcap and write the output to files
#   inv-yyyymmdd.csv and opt-yyyymmdd.csv with headers.
#    
#   seconvert2 -f -j solar.json
#
#   Monitor stdin and write the current values to
#   the file solar.json.
#    
#   seconvert2 -a -D"\t" -i inv.tsv -o opt.tsv test.pcap
#
#   Convert the file test.pcap and append the output to files
#   inv.tsv and opt.tsv with tab delimiters.

import os
import socket
import struct
import sys
import time
import getopt
import syslog
import json

# configuration
debug = False
debugFiles = False
debugRecs = False
debugData = False
debugRaw = False
debugSeq = []
inFileName = ""
inputSeq = 0
invFileName = ""
optFileName = ""
jsonFileName = ""
headers = False
delim = ","
writeMode = "w"
sleepInterval = 10
dbRetryInterval = 60
logSysout = False
printPtr = 0
recPtr = 0
inBuf = ""
lineSize = 16

# file handles
inFile = None
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

# SolarEdge data
def seConvert():
    global inputSeq, printPtr, recPtr, inBuf
    # skip to the start of the first record
    inBuf = inFile.read(4)
    while inBuf[-4:] != "\x12\x34\x56\x79":
        inBuf += inFile.read(1)
    printPtr = len(inBuf) - 4
    recPtr = printPtr
    inBuf += inFile.read(1)
    while True:
        while inBuf:
            inputSeq += 1
            if inBuf:
                # read 1 byte at a time until the next magic number
                while inBuf[-4:] != "\x12\x34\x56\x79":
                    readBytes(1)
                # start of new record
                # dump the remaining bytes
                printRaw(inBuf[printPtr:-4])
                printPtr = len(inBuf) - 4
                convertRec(inBuf[recPtr:printPtr])
                recPtr = printPtr
                readBytes(1)
        time.sleep(sleepInterval)

def readBytes(length):
    global printPtr, inBuf
    inBuf += inFile.read(length)
    if len(inBuf) - printPtr >= lineSize:
        printRaw(inBuf[printPtr:printPtr+lineSize])
        printPtr += lineSize

def printRaw(rec):
    if debugRaw: log("solaredge", "rawdata:", ' '.join(x.encode('hex') for x in rec))

def convertRec(rec):
    if debugData: log("solaredge", "record:", inputSeq, "length:", len(rec))
    dataPtr = 0
    while dataPtr < len(rec):
        if debugData: log("solaredge", "data[%02d]:" % (dataPtr/2), "%04x" % struct.unpack("<H", rec[dataPtr:dataPtr+2]))
        dataPtr = dataPtr + 2
    if debugData: log("solaredge")
    
# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# write device data to json file
def writeJson():
    if jsonFileName != "":
#        if debugFiles: log("writing", jsonFileName)
        json.dump({"inverters": invDict, "optimizers": optDict}, open(jsonFileName, "w"))
    
# write device data
def writeData(seId, seData, seIdx, outFmt, outFile):
    if outFile:
        outRec = outFmt % outData(seId, seData, seIdx)
        try:
            outFile.write(outRec+"\n")
            if debugRecs: log("writing", outRec)
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
    global writeMode, delim, follow, headers
    global invFileName, optFileName, jsonFileName
    global pcapDir, inFileName, inFiles, logSysout
    (opts, args) = getopt.getopt(sys.argv[1:], "aD:fp:Hi:j:lo:v")
    try:
        inFileName = args[0]
    except:
        inFileName = "stdin"      
    for opt in opts:
        if opt[0] == "-a":
            writeMode = "a"
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
        log("inFileName:", inFileName)
        log("invFileName:", invFileName)
        log("optFileName:", optFileName)
        log("jsonFileName:", jsonFileName)
        log("logSysout:", logSysout)

# open the output files if they are specified
def openOutFiles():
    global invFile, optFile
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

# open the specified input file
def openInFile(inFileName):
    global inFile, inputSeq
    if inFileName == "stdin":
        inFile = sys.stdin
    else:
        try:
            if debugFiles: log("opening", inFileName)
            inFile = open(inFileName)
            inputSeq = 0
        except:
            terminate(1, "Unable to open "+inFileName)

# close all files        
def closeFiles():
    if inFile: inFile.close()
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
        print message
    else:
        syslog.syslog(message)

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
    seConvert()
    closeFiles()
