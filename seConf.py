# SolarEdge configuration, logging, and debugging

import syslog
import sys
import time
import getopt
import sys
import socket
import netifaces

# debug flags
debugEnable = True
debugFiles = False
debugMsgs = False
debugData = False
debugRaw = False
logStdout = False
haltOnException = False

# data input parameters
inFileName = ""
following = False
baudRate = 115200
masterMode = False
slaveAddrs = []
restart = False
networkMode = False
serialDevice = False

# output file parameters
outFileName = ""
invFileName = ""
optFileName = ""
jsonFileName = ""
headers = False
delim = ","
writeMode = "w"

# global constants
bufSize = 1024
parsing = True
sleepInterval = .1
lineSize = 16
appName = "semonitor"
serialFileName = "/dev/tty"
readThreadName = "read thread"
masterThreadName = "master thread"
masterMsgInterval = 5
masterAddr = 0xfffffffe

# network constants
netInterface = ""
ipAddr = ""
broadcastAddr = ""
subnetMask = ""
sePort = 22222
dhcpDnsBufferSize = 4096
dhcpLeaseTime = 24*60*60    # 1 day
validMacs = ["\xb8\x27\xeb",   # Raspberry Pi
             "\x00\x27\x02",   # SolarEdge
             ]
dnsTtl = 24*60*60           # 1 day

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
(opts, args) = getopt.getopt(sys.argv[1:], "ab:D:fp:Hi:j:lmn:o:rs:vx")
try:
    inFileName = args[0]
    if inFileName == "-":
        inFileName = "stdin"
    if inFileName[0:len(serialFileName)] == serialFileName:
        serialDevice = True      
except:
    networkMode = True
    inFileName = "network"
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
        try:
            # network interface parameters
            netInterface = opt[1]
            netInterfaceParams = netifaces.ifaddresses(netInterface)[2][0]
            ipAddr = netInterfaceParams["addr"]
            broadcastAddr = netInterfaceParams["broadcast"]
            subnetMask = netInterfaceParams["netmask"]
        except:
            terminate(1, "network interface is not available")
    elif opt[0] == "-o":
        optFileName = opt[1]
    elif opt[0] == "-r":
        restart = True
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

# force following for input from serial device
if serialDevice:
    following = True

# network mode implies master mode
if networkMode:
    masterMode = True
elif masterMode and not serialDevice:
    terminate(1, "Master mode not allowed with file input")
   
# determine if data is going to need to be parsed
if (outFileName != "") and (invFileName == "") and (optFileName == "") and (jsonFileName == "") and not masterMode:
    parsing = False

if debugFiles: 
    log("debugEnable:", debugEnable)  
    log("debugFiles:", debugFiles)  
    log("debugMsgs:", debugMsgs)
    log("debugData:", debugData)
    log("debugRaw:", debugRaw)
    log("logStdout:", logStdout)
    log("haltOnException:", haltOnException)
    log("following:", following)
    log("parsing:", parsing)
    log("inFileName:", inFileName)
    log("serialDevice:", serialDevice)
    if serialDevice:
        log("baudRate:", baudRate)
    log("restart:", restart)
    log("masterMode:", masterMode)
    if masterMode:
        log("slaveAddrs:", slaveAddrs)
    log("networkMode:", networkMode)
    if netInterface != "":
        log("netInterface", netInterface)
        log("ipAddr", ipAddr)
        log("subnetMask", subnetMask)
        log("broadcastAddr", broadcastAddr)
    log("outFileName:", outFileName)
    log("invFileName:", invFileName)
    log("optFileName:", optFileName)
    if (invFileName != "") or (optFileName != ""):
        log("headers:", headers)
        log("delim:", delim)
    log("append:", writeMode)
    log("jsonFileName:", jsonFileName)

