#!/usr/bin/python

# Read a file that is a capture of the TCP stream from a SolarEdge inverter to the SE server.
# Filter out and parse the log data for inverters and optimizers.

# The output can be specified in various modes:
# 1. batch - output is written to csv files
# 2. realtime - output is loaded into a database

# Usage: seconvert2 [-a] [-d database] [-f] [-H] [-h hostname] [-i invfile] [-o optfile] 
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
#   -d database     database name
#   -f              output appended data as the pcap file grows (as in tail -f)
#   -H              write column headers to output files
#   -h hostname     database hostname or IP address
#   -i invfile      inverter file to write
#   -j jsonfile     json file to write current values to
#   -l              send logging messages to sysout
#   -o optfile      optimizer file to write
#   -p passwd       database password
#   -u username     database username
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
#    
#   seconvert2 -f -d solar -h dbhost
#
#   Monitor stdin and write the converted output into
#   database "solar" on hostname "dbhost".  No output files are written.

import os
import socket
import struct
import sys
import time
import getopt
import MySQLdb
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
dataBase = ""
dbHostName = ""
userName = ""
password = ""
sleepInterval = 10
dbRetryInterval = 60
logSysout = False

# file handles
inFile = None
invFile = None
optFile = None
jsonFile = None
db = None

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
invSqlFmt = "Date='%s',Time='%s',ID='%s',Uptime=%d,Intrvl=%d,Temp=%f,Eday=%f,Eint=%f,Vac=%f,Iac=%f,Freq=%f,Vdc=%f,Etot=%f,Pmax=%f,Pac=%f"
optSqlFmt = "Date='%s',Time='%s',ID='%s',Inv='%s',Uptime=%d,Vmod=%f,Vopt=%f,Imod=%f,Eday=%f,Temp=%f"
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
    global inputSeq
    inRec = readBytes(4)
    while True:
        while inRec:
            seHeader(inRec+readBytes(2))
            inputSeq += 1
            inRec = readBytes(4)
            if inRec:
                # read 1 byte at a time until the next magic number
                while inRec != "\x12\x34\x56\x79":
                    inRec = inRec[1:4]+readBytes(1)
        time.sleep(sleepInterval)

def seHeader(inRec):
    global invDict, optDict
    # read the header record
    (seMagic, seDataLen) = struct.unpack("<LH", inRec)
    if debugData: log("solaredge", "inputSeq", inputSeq, "seDataLen", seDataLen)
    if (seMagic != 0x79563412) or (seDataLen == 0):     # is it a solaredge record that is non-zero length
        return
    try:
        seHdr = struct.unpack("<BBHLLH", readBytes(seHdrLen-6))
    except:
        return
    if debugData: log("solaredge", "    seHdr", "%02x %02x %04x %08x %08x %04x" % seHdr)
    # ignore records that aren't type 0xfe or are shorter than a device record
    if (seDataLen < seDevHdrLen) or (seHdr[1] != 0xfe):
        seData = readBytes(seDataLen)
        seDataLen = 0
    else:
        while seDataLen > 0:
            # process a device record
            seDevice = struct.unpack("<HLH", readBytes(seDevHdrLen))
            seType = seDevice[0]
            seId = convertId(seDevice[1])
            seDeviceLen = seDevice[2]
            if debugData: log("solaredge", "        seType", "%04x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
            if seType == 0x0000:    # optimizer log data
                seOptData = readData(inFile, optInFmt, seDeviceLen)
                seOptData[2] = convertId(seOptData[2])
                optDict[seId] = optDictData(seOptData)
                writeJson()
                writeData(seId, seOptData, optIdx, optOutFmt, optFile)
                writeDb(seId, seOptData, optIdx, optSqlFmt, "optimizers")
            elif seType == 0x0080:  # new format optimizer log data
                seData = readBytes(seDeviceLen)
                seOptData = convertNewOptData(seData)
                optDict[seId] = optDictData(seOptData)
                writeJson()
                writeData(seId, seOptData, optIdx, optOutFmt, optFile)
                writeDb(seId, seOptData, optIdx, optSqlFmt, "optimizers")
            elif seType == 0x0010:  # inverter log data
                seInvData = readData(inFile, invInFmt, seDeviceLen)
                invDict[seId] = invDictData(seInvData)
                writeJson()
                writeData(seId, seInvData, invIdx, invOutFmt, invFile)
                writeDb(seId, seInvData, invIdx, invSqlFmt, "inverters")
            else:
                if not debugData: log("solaredge", "unknown seType", "%04x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
                seData = readBytes(seDeviceLen)
            seDataLen -= seDeviceLen + seDevHdrLen
    seCksum = struct.unpack("!H", readBytes(2))
    if debugData: log("solaredge", "    seCksum", "%04x" % seCksum, "seDataLen", seDataLen)

def readBytes(length):
    msg = inFile.read(length)
    if debugRaw: log("solaredge", "rawdata:", ' '.join(x.encode('hex') for x in msg))
    return msg
    
# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

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

# read device data    
def readData(inFile, inFmt, seDeviceLen):
    return list(struct.unpack(inFmt, readBytes(seDeviceLen)[:(len(inFmt)-1)*4]))

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

# write device data to database
def writeDb(seId, seData, seIdx, sqlFmt, table):
    if db:
        # add a new record to the device history table
        sql = "insert ignore "+table+" set "+sqlFmt % outData(seId, seData, seIdx)+";"
        rows = 0
        while rows == 0:
            try:
                if debugRecs: log("sql", sql)
                cursor = db.cursor()
                rows = cursor.execute(sql)
                db.commit()
                cursor.close()
                rows = 1
            except MySQLdb.IntegrityError:  # ignore duplicate entries
                if debugRecs: log("duplicate")
                rows = 1
            except:
                log("warning", "Error writing to database - retrying in", dbRetryInterval, "seconds")
                time.sleep(dbRetryInterval)
                openDb()

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
    global dataBase, dbHostName, password
    global userName, pcapDir, inFileName, inFiles, logSysout
    (opts, args) = getopt.getopt(sys.argv[1:], "aD:d:fp:Hh:i:j:lo:p:u:v")
    try:
        inFileName = args[0]
    except:
        inFileName = "stdin"      
    for opt in opts:
        if opt[0] == "-a":
            writeMode = "a"
        elif opt[0] == "-D":
            delim = opt[1] 
        elif opt[0] == "-d":
            dataBase = opt[1] 
        elif opt[0] == "-f":
            follow = True
        elif opt[0] == "-H":
            headers = True
        elif opt[0] == "-h":
            dbHostName = opt[1]
        elif opt[0] == "-i":
            invFileName = opt[1]
        elif opt[0] == "-j":
            jsonFileName = opt[1]
        elif opt[0] == "-l":
            logSysout = True
        elif opt[0] == "-o":
            optFileName = opt[1]
        elif opt[0] == "-p":
            password = opt[1]
        elif opt[0] == "-u":
            userName = opt[1]
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
        log("dataBase:", dataBase)
        log("dbHostName:", dbHostName)
        log("userName:", userName)
        log("password:", password)
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

# open the connection to the database
def openDb():
    global db
    if dataBase != "":
        while not db:
            try:
                if debugFiles: log("database", dataBase+" as "+userName+" on "+dbHostName)
                db = MySQLdb.connect(host=dbHostName, user=userName, passwd=password, db=dataBase)
            except:
                log("warning", "Error opening database - retrying in", dbRetryInterval, "seconds")
                time.sleep(dbRetryInterval)

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
    if db: db.close()

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
    openDb()
    # process the input file
    if debugFiles: log("reading", inFileName)
    openInFile(inFileName)
    seConvert()
    closeFiles()
