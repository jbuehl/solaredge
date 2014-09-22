#!/usr/bin/python

# Read a PCAP file that is a capture of the traffic between a SolarEdge inverter and the SE server.
# Filter out and parse the log data for inverters and optimizers.

# The output can be specified in various modes:
# 1. batch - output is written to csv files
# 2. realtime - output is loaded into a database

# Usage: seconvert [-a] [-d database] [-f] [-H] [-h hostname] [-i invfile] [-o optfile] 
#                  [-p passwd] [-s server] [-u username] [-v] pcapFile
# Arguments:
#   pcapFile        pcap file or directory to read
#                   If a file is specified, the program processes the data in that file and
#                   terminates, unless the -f option is specified, in which case it waits for 
#                   further data to be written to the pcap file.
#                   If a directory is specified, all files in the directory are processed.
#                   If a directory is specified and the -f option is specified, only the file
#                   in the directory with the newest modified date is processed and the program
#                   waits for further data in that file.  If a new file is subsequently created in
#                   the directory, the current file is closed and the new file is opened. 
# Options:
#   -a              append to output files
#   -D delim        output file delimiter (default: ",")
#   -d database     database name
#   -f              output appended data as the pcap file grows (as in tail -f)
#   -H              write column headers to output files
#   -h hostname     database hostname or IP address
#   -i invfile      inverter file to write
#   -o optfile      optimizer file to write
#   -p passwd       database password
#   -s server       SolarEdge server hostname or IP address (default: prod.solaredge.com)
#   -u username     database username
#   -v              verbose output

# Examples:
#   seconvert -H pcap-20140122000001.pcap
#
#   Convert the data in file pcap-20140122000001.pcap and write the output to files
#   inv-yyyymmdd.csv and opt-yyyymmdd.csv with headers.
#    
#   seconvert -H -i inv/ -o opt/ pcap/
#
#   Convert all the pcap files found in directory pcap/ and write the output to files
#   inv/inv-yyyymmdd.csv and opt/opt-yyyymmdd.csv with headers.
#    
#   seconvert -a -D"\t" -i inv.tsv -o opt.tsv pcap/
#
#   Convert all the pcap files found in directory pcap/ and append the output to files
#   inv.tsv and opt.tsv with tab delimiters.
#    
#   seconvert -f -d solar -h dbhost pcap/
#
#   Monitor PCAP files in directory pcap/ and write the converted output into
#   database "solar" on hostname "dbhost".  No output files are written.

import os
import socket
import struct
import sys
import time
import StringIO
import getopt
import MySQLdb
import syslog

# configuration
debug = False
debugFiles = False
debugRecs = False
debugData = False
debugSeq = []
seHostName = "prod.solaredge.com"
pcapDir = ""
pcapFiles = []
pcapFileName = ""
pcapSeq = 0
invFileName = ""
optFileName = ""
headers = False
follow = False
delim = ","
writeMode = "w"
dataBase = ""
dbHostName = ""
userName = ""
password = ""
sleepInterval = 10
dbRetryInterval = 60

# file handles
pcapFile = None
invFile = None
optFile = None
db = None

# file constants
pcapFileHdrLen = 24
pcapRecHdrLen = 16
etherHdrLen = 14
ipHdrLen = 20
tcpHdrLen = 20
seHdrLen = 20
seDevHdrLen = 8

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

# PCAP file header
def readPcapFileHdr(pcapFile):
    return struct.unpack("<LHHLLLL", pcapFile.read(pcapFileHdrLen))

# PCAP record header
def readPcapRecHdr(pcapFile):
    pcapBuf = pcapFile.read(pcapRecHdrLen)
    if pcapBuf:
        return struct.unpack("<LLLL", pcapBuf)
    else:
        return None
# PCAP record
def readPcapRec(pcapFile):
    global pcapSeq, debugData
    pcapSeq += 1
    # if sequence numbers were specified turn debugData on or off
    if debugSeq != []:
        if pcapSeq in debugSeq: debugData = True
        else:                   debugData = False
    pcapRecLen = pcapRec[2]
    # strip off ethernet, IP, and TCP headers
    etherHdr = readEtherHdr(pcapFile)
    ipHdr = readIpHdr(pcapFile)
    tcpHdr = readTcpHdr(pcapFile)
    # data is whatever is left
    dataLen = pcapRecLen - etherHdrLen - ipHdrLen - tcpHdrLen
    if debugData: log("pcap", "pcapSeq", pcapSeq, "pcapRecLen", pcapRecLen, "dataLen", dataLen)
    if dataLen > 0:
        if ipHdr[4] == seIpAddr:   # only process records where IP dest is SE server
            readSe(StringIO.StringIO(pcapFile.read(dataLen)), invFile, optFile)
        else:   # ? FIXME
            pcapFile.read(dataLen)

# Ethernet header    
def readEtherHdr(pcapFile):
    return pcapFile.read(etherHdrLen)

# IP header
def readIpHdr(pcapFile):
    return struct.unpack("!LLLLL", pcapFile.read(ipHdrLen))
    
# TCP header
def readTcpHdr(pcapFile):
    return struct.unpack("<LLLLL", pcapFile.read(tcpHdrLen))

# SolarEdge data
def readSe(pcapFile, invFile, optFile):
    # read the header record
    (seMagic, seDataLen) = struct.unpack("<LH", pcapFile.read(6))
    if debugData: log("solaredge", "seMagic", "%x" % seMagic, "seDataLen", seDataLen)
    if (seMagic != 0x79563412) or (seDataLen == 0):     # is it a solaredge record that is non-zero length
        return
    try:
        seHdr = struct.unpack("<BBHHHHHH", pcapFile.read(seHdrLen-6))
    except:
        return
    if debugData: log("solaredge", "seHdr", "%x "*8 % seHdr)
    # ignore records that aren't type 0xfe or are shorter than a device record
    if (seDataLen < seDevHdrLen) or (seHdr[1] != 0xfe):
        seData = pcapFile.read(seDataLen)
        seDataLen = 0
    else:
        while seDataLen > 0:
            # process a device record
            seDevice = struct.unpack("<HLH", pcapFile.read(seDevHdrLen))
            seType = seDevice[0]
            seId = convertId(seDevice[1])
            seDeviceLen = seDevice[2]
            if debugData: log("solaredge", "seType", "%4x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
            if seType == 0x0000:    # optimizer log data
                seOptData = readData(pcapFile, optInFmt, seDeviceLen)
                seOptData[2] = convertId(seOptData[2])
                writeData(seId, seOptData, optIdx, optOutFmt, optFile)
                writeDb(seId, seOptData, optIdx, optSqlFmt, "optimizers")
            elif seType == 0x0010:  # inverter log data
                seInvData = readData(pcapFile, invInFmt, seDeviceLen)
                writeData(seId, seInvData, invIdx, invOutFmt, invFile)
                writeDb(seId, seInvData, invIdx, invSqlFmt, "inverters")
            elif seType == 0x0200:
                if debug: log("unknown:", "pcapSeq", pcapSeq, "seType", "%4x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
                seData = pcapFile.read(seDeviceLen)
            elif seType == 0x0300:
                if debug: log("unknown:", "pcapSeq", pcapSeq, "seType", "%4x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
                seData = pcapFile.read(seDeviceLen)
            else:
                if debug: log("unknown:", "pcapSeq", pcapSeq, "seType", "%4x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
                seData = pcapFile.read(seDataLen - seDevHdrLen)
            seDataLen -= seDeviceLen + seDevHdrLen
#        if db:
#            try:
#                sql = """
#                    drop table if exists stats;
#                    create table stats select inv.eday Eday, mon.emon Emonth, yr.eyr Eyear, inv.etot Elifetime, inv.temp Tinv, opt.temp Topt from
#	                    (select sum(Eday) eday, sum(Etot) etot, avg(Temp) temp from invstate) inv
#	                    join
#	                    (select avg(Temp) temp from optstate) opt
#	                    join
#	                    (select sum(eday.Eday) emon from
#		                    (select date, id, max(eday) eday from inverters 
#			                    where month(date) = month(now())
#			                    group by date, id) eday) mon
#	                    join
#	                    (select sum(eday.Eday) eyr from
#		                    (select date, id, max(eday) eday from inverters 
#			                    where year(date) = year(now())
#			                    group by date, id) eday) yr;
#                    """
#                cursor = db.cursor()
#                rows = cursor.execute(sql)
#                if debugRecs: log("sql", sql)
#                db.commit()
#                cursor.close()
#            except:
#                pass
    seCksum = struct.unpack("!H", pcapFile.read(2))
    if seDataLen:
        if debugData: log("solaredge", "len", seDataLen, "cksum", "%x" % seCksum)

# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# read device data    
def readData(pcapFile, inFmt, seDeviceLen):
    return list(struct.unpack(inFmt, pcapFile.read(seDeviceLen)))

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
        insertSql = "insert ignore "+table+" set "+sqlFmt % outData(seId, seData, seIdx)+";"
#        # update the current device state
#        updateSql = "update ignore "+table[0:3]+"state set "+sqlFmt % outData(seId, seData, seIdx)+" where id='"+seId+"';"
        rows = 0
        while rows == 0:
            try:
                cursor = db.cursor()
#                rows = cursor.execute(updateSql)
#                if debugRecs: log("sql", updateSql)
                rows = cursor.execute(insertSql)
                if debugRecs: log("sql", insertSql)
                db.commit()
                cursor.close()
                rows = 1
            except MySQLdb.IntegrityError:  # ignore duplicate entries
                if debugRecs: log("duplicate", sql)
                rows = 1
            except:
                print "Error writing to database - retrying in", dbRetryInterval, "seconds"
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
    global debug, debugFiles, debugRecs, debugData
    global writeMode, delim, follow, headers
    global invFileName, optFileName
    global dataBase, dbHostName, password, seHostName, seIpAddr
    global userName, pcapDir, pcapFileName, pcapFiles
    (opts, args) = getopt.getopt(sys.argv[1:], "aD:d:fp:Hh:i:o:p:s:u:v")
    try:
        pcapFileName = args[0]
        if os.path.isdir(pcapFileName): # a directory was specified
            pcapDir = pcapFileName.strip("/")+"/"
            pcapFiles = os.listdir(pcapDir)
        else:                           # a file was specified
            pcapDir = ""
            pcapFiles = [pcapFileName]       
    except:
        terminate(1, "PCAP file must be specified")        
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
        elif opt[0] == "-o":
            optFileName = opt[1]
        elif opt[0] == "-p":
            password = opt[1]
        elif opt[0] == "-s":
            seHostName = opt[1]
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
    if debug:
        log("debug:", debug)  
        log("debugFiles:", debugFiles)  
        log("debugData:", debugData)
        log("follow:", follow)
        log("headers:", headers)
        log("server:", seHostName)
        log("delim:", delim)
        log("dataBase:", dataBase)
        log("dbHostName:", dbHostName)
        log("userName:", userName)
        log("password:", password)
        log("append:", writeMode)
        log("pcapFileName:", pcapFileName)
        log("invFileName:", invFileName)
        log("optFileName:", optFileName)
    # get the IP address of the SolarEdge server
    try:    
        seIpAddr = struct.unpack("!I", socket.inet_aton(socket.gethostbyname_ex(seHostName)[2][0]))[0]    # 0xd9449842
    except:
        print "Unable to resolve hostname", seHostName        

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
        try:
            if debugFiles: log("database", dataBase)
            db = MySQLdb.connect(host=dbHostName, user=userName, passwd=password, db=dataBase)
        except:
            terminate(1, "Unable to open database "+dataBase+" as "+userName+" on "+dbHostName) 

# open the specified pcap file
def openPcapFile(pcapFileName):
    global pcapFile, pcapSeq
    try:
        if debugFiles: log("opening", pcapFileName)
        pcapFile = open(pcapFileName)
        pcapHdr = readPcapFileHdr(pcapFile) # ignore the pcap file header
        pcapSeq = 0
    except:
        terminate(1, "Unable to open "+pcapFileName)

# close the currently open pcap file
def closePcapFile():
    if debugFiles: log("closing", pcapFileName, pcapSeq, "records")
    pcapFile.close()

# open the last modified file in the pcap directory
def openLastPcapFile():
    global pcapFileName, pcapDir, pcapFile
    if pcapDir != "":   # directory was specified
        try:
            pcapFiles = os.listdir(pcapDir)
        except:
            terminate(1, "Unable to access directory "+pcapDir)
        latestModTime = 0
        # find the name of the file with the largest modified time
        for fileName in pcapFiles:
            pcapModTime = os.path.getmtime(pcapDir+fileName)
            if pcapModTime > latestModTime:
               latestModTime = pcapModTime 
               latestFileName = pcapDir+fileName
        if pcapFileName != latestFileName:  # is there a new file?
            if pcapFile:                    # is a file currently open?
                closePcapFile()
            pcapFileName = latestFileName
            openPcapFile(pcapFileName)
    else:   # just open the specified file the first time this is called
        if not pcapFile:
            openPcapFile(pcapFileName)

# close all files        
def closeFiles():
    if pcapFile: pcapFile.close()
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
#    print message
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
    # process the pcap file(s)
    if follow:      # following - start
        # open the latest pcap file in the pcap directory   
        openLastPcapFile()
        while True: # read forever
            pcapRec = readPcapRecHdr(pcapFile)
            if pcapRec:
                readPcapRec(pcapFile)
            else:   # end of file - wait a bit and see if there is more data
                time.sleep(sleepInterval)
                openLastPcapFile()
    else:       # not following - process whatever files were specified and exit 
        for pcapFileName in pcapFiles:
            if debugFiles: log("reading", pcapDir+pcapFileName)
            openPcapFile(pcapDir+pcapFileName)
            pcapRec = readPcapRecHdr(pcapFile)
            pcapSeq = 0
            while pcapRec:
                readPcapRec(pcapFile)
                pcapRec = readPcapRecHdr(pcapFile)
            closePcapFile()
        closeFiles()
