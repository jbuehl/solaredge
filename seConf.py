# SolarEdge configuration, logging, and debugging

import syslog
import sys
import time
import getopt
import sys
import socket
import netifaces
import os
import signal
import serial.tools.list_ports

# debug flags
debugEnable = True
debugFiles = False
debugMsgs = False
debugData = False
debugRaw = False
logStdout = False
haltOnException = False

# data source parameters
inFileName = ""
following = False
serialDevice = False
baudRate = 115200
networkDevice = False

# operating mode paramaters
passiveMode = True
masterMode = False
slaveAddrs = []

# action parameters
commandAction = False
commands = ""
commandDelay = 2
networkInterface = ""
networkSvcs = False

# output file parameters
outFileName = ""
invFileName = ""
optFileName = ""
jsonFileName = ""
headers = False
delim = ","
writeMode = "w"
updateFileName = ""

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
seqFileName = "seseq.txt"
updateSize = 0x80000

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
        if direction == "-->" and debugData:
            log(" ")
        log(endPoint, direction, "message:", seq, "length:", len(msg))
        if debugRaw:
            logData(msg)
        if direction == "<--" and debugData:
            log(" ")

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

# get next sequence number
def nextSeq():
    try:
        with open(seqFileName) as seqFile:
            seq = int(seqFile.read().rstrip("\n"))
        seq += 1
    except:
        seq = 1
    with open(seqFileName, "w") as seqFile:
        seqFile.write(str(seq)+"\n")
    return seq

# block while waiting for a keyboard interrupt
def waitForEnd():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # commit suicide
        os.kill(os.getpid(), signal.SIGKILL)
        return False

# parse and validate the commands specified in the -c option
def parseCommands(opt):
    try:
        commands = [command.split(",") for command in opt.split("/")]
        for command in commands:
            try:
                # validate the command function
                v = int(command[0],16)
                # validate command parameters
                for p in command[1:]:
                    # validate data type
                    if p[0] not in "bhlBHL":
                        log(" ".join(c for c in command))
                        terminate(1, "Invalid data type "+p[0])
                    # validate parameter value
                    v = int(p[1:],16)
            except ValueError:
                log(" ".join(c for c in command))
                terminate(1, "Invalid numeric value")
    except:
        raise
        terminate(1, "Error parsing commands")
    return commands
                        
# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "ab:c:D:fp:Hi:j:lmn:o:s:u:vx")

# figure out the list of valid serial ports
try:
    serialPortNames = []
    serialPorts = serial.tools.list_ports.comports()
    # this is either a list of tuples or ListPortInfo objects
    if isinstance(serialPorts[0], tuple):
        for serialPort in serialPorts:
            serialPortNames.append(serialPort[0])
    elif isinstance(serialPorts[0], serial.tools.list_ports_common.ListPortInfo):
        for serialPort in serialPorts:
            serialPortNames.append(serialPort.device)
except:
    pass

try:
    inFileName = args[0]
    if inFileName == "-":
        inFileName = "stdin"
    elif inFileName in serialPortNames:
        serialDevice = True      
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
    elif opt[0] == "-c":
        commandAction = True
        commands = parseCommands(opt[1])
        passiveMode = False 
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
        passiveMode = False
    elif opt[0] == "-n":
        networkDevice = True
        inFileName = "network"
        passiveMode = False
        try:
            netInterface = opt[1]
        except:
            pass
    elif opt[0] == "-o":
        optFileName = opt[1]
    elif opt[0] == "-s":
        slaveAddrs = opt[1].split(",")
    elif opt[0] == "-u":
        updateFileName = opt[1]
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

# check for network device
if netInterface != "":
    try:
        netInterfaceParams = netifaces.ifaddresses(netInterface)[2][0]
        ipAddr = netInterfaceParams["addr"]
        broadcastAddr = netInterfaceParams["broadcast"]
        subnetMask = netInterfaceParams["netmask"]
        networkSvcs = True
    except:
        raise
        terminate(1, "network interface is not available")

# force following for input from serial device
if serialDevice or networkDevice:
    following = True

# master mode is only for serial device
if masterMode and not serialDevice:
    terminate(1, "Master mode only allowed with serial device")

# master and network mode require slaves to be specified
if masterMode and (len(slaveAddrs) < 1):
    terminate(1, "At least one slave address must be specified for master mode")
if commandAction and (len(slaveAddrs) != 1):
    terminate(1, "Exactly one slave address must be specified for command mode")
       
if debugFiles: 
    log("debugEnable:", debugEnable)  
    log("debugFiles:", debugFiles)  
    log("debugMsgs:", debugMsgs)
    log("debugData:", debugData)
    log("debugRaw:", debugRaw)
    log("logStdout:", logStdout)
    log("haltOnException:", haltOnException)
    log("inFileName:", inFileName)
    log("serialDevice:", serialDevice)
    if serialDevice:
        log("    baudRate:", baudRate)
    log("following:", following)
    log("passiveMode:", passiveMode)
    log("commandAction:", commandAction)
    if commandAction:
        for command in commands:
            log("    command:", " ".join(c for c in command))
    log("masterMode:", masterMode)
    log("networkDevice:", networkDevice)
    if masterMode or networkDevice:
        log("slaveAddrs:", ",".join(slaveAddr for slaveAddr in slaveAddrs))
    log("networkSvcs:", networkSvcs)
    if networkSvcs:
        log("netInterface", netInterface)
        log("    ipAddr", ipAddr)
        log("    subnetMask", subnetMask)
        log("    broadcastAddr", broadcastAddr)
    if outFileName != "":
        log("outFileName:", outFileName)
    if invFileName != "":
        log("invFileName:", invFileName)
    if optFileName != "":
        log("optFileName:", optFileName)
    if (invFileName != "") or (optFileName != ""):
        log("    headers:", headers)
        log("    delim:", delim)
    if jsonFileName != "":
        log("jsonFileName:", jsonFileName)
    log("append:", writeMode)
    if updateFileName != "":
        log("updateFileName:", updateFileName)

