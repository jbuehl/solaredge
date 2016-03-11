#!/usr/bin/python

# Read a PCAP file that is a capture of the traffic between a SolarEdge inverter and the SE server.
# Filter out the TCP stream between the inverter to the server.

# Usage: python seextract.py [-a] [-f] [-o outFile] 
#                 [-s server] [-v] pcapFile
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
#   -f              output appended data as the pcap file grows (as in tail -f)
#   -o outfile      output file to write
#   -s server       SolarEdge server hostname or IP address (default: prod.solaredge.com)
#   -v              verbose output

# Examples:
#   # python seextract.py -o test.pcap pcap-20140122000001.pcap
#
#   Convert the data in file pcap-20140122000001.pcap and write the output to file
#   test.pcap
#    
#   # python seextract.py -f pcap/
#
#   Monitor PCAP files in directory pcap/ and write the current values to stdin.
#    
#   # python seextract.py -o allfiles.pcap pcap/
#
#   Convert all the pcap files found in directory pcap/ and write the output to files
#   allfiles.pcap.

import os
import socket
import struct
import sys
import time
import getopt
import syslog

# configuration
debug = False
debugFiles = False
debugRecs = False
debugData = False
debugSeq = []
seHostName = ""
seIpAddr = 0
pcapDir = ""
pcapFiles = []
pcapFileName = ""
pcapSeq = 0
outFileName = ""
follow = False
writeMode = "w"
sleepInterval = 10

# file handles
pcapFile = None
outFile = None

# file constants
pcapFileHdrLen = 24
pcapRecHdrLen = 16
etherHdrLen = 14
ipHdrLen = 20
tcpHdrLen = 20

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
    if debugData: log("pcap", "pcapSeq", pcapSeq, "srcIp", ip2str(ipHdr[3]), "dstIp", ip2str(ipHdr[4]), "pcapRecLen", pcapRecLen, "dataLen", dataLen)
    if dataLen > 0:
        if (seIpAddr == 0) or (ipHdr[4] == seIpAddr):   # only process records where IP dest is SE server
            if outFile:
                outFile.write(pcapFile.read(dataLen))
            else:
                sys.stdout.write(pcapFile.read(dataLen))
                sys.stdout.flush()
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

# get command line options and arguments
def getOpts():
    global debug, debugFiles, debugRecs, debugData
    global writeMode, follow
    global outFileName
    global seHostName, seIpAddr
    global pcapDir, pcapFileName, pcapFiles
    (opts, args) = getopt.getopt(sys.argv[1:], "afo:s:v")
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
        elif opt[0] == "-f":
            follow = True
        elif opt[0] == "-o":
            outFileName = opt[1]
        elif opt[0] == "-s":
            seHostName = opt[1]
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
        log("server:", seHostName)
        log("append:", writeMode)
        log("pcapFileName:", pcapFileName)
        log("outFileName:", outFileName)
    # get the IP address of the SolarEdge server
    try:
        if seHostName != "":    
            seIpAddr = struct.unpack("!I", socket.inet_aton(socket.gethostbyname_ex(seHostName)[2][0]))[0]    # 0xd9449842
            log("serverIpAddr:", ip2str(seIpAddr))
    except:
        print "Unable to resolve hostname", seHostName        

# open the output file if it is specified
def openOutFile():
    global outFile
    if outFileName != "":
        try:
            if debugFiles: log("writing", outFileName)
            outFile = open(outFileName, writeMode)
        except:
            terminate(1, "Unable to open "+outFileName)

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
    if outFile: outFile.close()

def log(*args):
    message = args[0]+" "
    for arg in args[1:]:
        message += arg.__str__()+" "
#    print message
    syslog.syslog(message)

def ip2str(ipAddr):
    return "%d.%d.%d.%d" % struct.unpack("!BBBB", struct.pack("!L", ipAddr))
    
def terminate(code, msg=""):
    print msg
    sys.exit(code)
    
if __name__ == "__main__":
    getOpts()         
    # open output
    openOutFile()
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
