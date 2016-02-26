# SolarEdge configuration, logging, and debugging

import syslog
import sys
import time
import getopt
import sys
import socket

# debugging
debugEnable = True
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
haltOnException = False
baudRate = 115200
masterMode = False
slaveAddrs = []
networkMode = False
logStdout = False

# global variables and constants
bufSize = 1024
parsing = True
waiting = True
sleepInterval = .1
lineSize = 16
appName = "semonitor"
serialFileName = "/dev/tty"
masterThreadName = "master"
masterMsgInterval = 5
masterAddr = 0xfffffffe

# network constants
thisIpAddr = socket.inet_aton("0.0.0.0")
sePort = 22222
dhcpDnsBufferSize = 4096
dhcpLeaseTime = 24*60*60
validMac = "\xb8\x27\xeb"
validMac = "\x00\x27\x02"
dnsTtl = 24*60*60

# log a message
def log(*args):
    message = args[0]+" "
    for arg in args[1:]:
        message += arg.__str__()+" "
    if logStdout:
        print time.asctime(time.localtime())+" "+message
    else:
        syslog.syslog(appName+" "+message)

# log a debug message
def debug(*args):
    if debugEnable:   # global debug flag enables debugging
        try:
            if globals()[args[0]]:  # arg[0] is debug level name
                log(*args[1:])
        except:
            pass
            
# log an incoming or outgoing data message
def logMsg(direction, seq, msg, endPoint=""):
    if debugMsgs:
#        log(" ")
        log(endPoint, direction, "message:", seq, "length:", len(msg))
    if debugRaw:
        logData(msg)

# program termination
def terminate(code=0, msg=""):
    log(msg)
    sys.exit(code)
    
# hex dump data
def logData(data):
    def logLine(data):
        log("data:      ", ' '.join(x.encode('hex') for x in data))
    if data != "":
        printPtr = 0
        while len(data) - printPtr >= lineSize:
            logLine(data[printPtr:printPtr+lineSize])
            printPtr += lineSize
        if printPtr < len(data):
            logLine(data[printPtr:])

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "ab:D:fp:Hi:j:lmn:o:s:vx")
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
        logStdout = True
    elif opt[0] == "-m":
        masterMode = True
    elif opt[0] == "-n":
        networkMode = True
        thisIpAddr = socket.inet_aton(opt[1])
    elif opt[0] == "-o":
        optFileName = opt[1]
    elif opt[0] == "-s":
        slaveAddrs = opt[1].split(",")
    elif opt[0] == "-v":
        if debugEnable:
            if not debugFiles:
                debugFiles = True   # -v
            elif not debugMsgs:
                debugMsgs = True    # -vv
            elif not debugData:
                debugData = True    # -vvv
            elif not debugRaw:
                debugRaw = True    # -vvvv
    elif opt[0] == "-x":
        haltOnException = True

# force following for input from stdin or serial device
if (inFileName == "stdin") or (inFileName[0:len(serialFileName)] == serialFileName):
    following = True

# determine if data is going to need to be parsed
if (outFileName != "") and (invFileName == "") and (optFileName == "") and (jsonFileName == ""):
    parsing = False

# network mode implies master mode
if networkMode:
    masterMode = True
    
if debugFiles: 
    log("debugEnable:", debugEnable)  
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
    log("logStdout:", logStdout)
    log("masterMode:", masterMode)
    log("slaveAddrs:", slaveAddrs)
    log("haltOnException:", haltOnException)
    log("networkMode:", networkMode)
    log("thisIpAddr:", socket.inet_ntoa(thisIpAddr))

