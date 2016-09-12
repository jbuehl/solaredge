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
debugFileName = "syslog"
debugFile = None
haltOnException = False

# data source parameters
inFileName = ""
following = False
inputType = ""
serialDevice = False
baudRate = 115200
networkDevice = False

# operating mode paramaters
passiveMode = True
masterMode = False
slaveAddrs = []

# action parameters
commandAction = False
commandStr = ""
commands = []
commandDelay = 2
networkInterface = ""
networkSvcs = False

# output file parameters
outFileName = "stdout"
recFileName = ""
writeMode = "w"
updateFileName = ""

# encryption key
keyFileName = ""
keyStr = ""

# global constants
bufSize = 1024
parsing = True
sleepInterval = .1
lineSize = 16
readThreadName = "read thread"
masterThreadName = "master thread"
masterMsgInterval = 5
masterMsgTimeout = 10
masterAddr = 0xfffffffe
seqFileName = "seseq.txt"
updateSize = 0x80000

# network constants
netInterface = ""
ipAddr = ""
broadcastAddr = ""
subnetMask = ""
sePort = 22222
socketTimeout = 120.0
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
    if debugFile:
        debugFile.write(time.strftime('%b %d %H:%M:%S',time.localtime())+" "+message+"\n")
        debugFile.flush()
    else:
        syslog.syslog(message)

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
        if seq > 65535:
            seq = 1
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
        terminate(1, "Error parsing commands")
    return commands
                        
# figure out the list of valid serial ports on this server
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

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "ab:c:d:fk:mn:o:p:r:s:t:u:vx")
# arguments
try:
    inFileName = args[0]
    if inFileName == "-":
        inFileName = "stdin"
    elif inFileName in serialPortNames:
        serialDevice = True      
except:
        inFileName = "stdin"
        following = True
# options
for opt in opts:
    if opt[0] == "-a":
        writeMode = "a"
    elif opt[0] == "-b":
        baudRate = opt[1] 
    elif opt[0] == "-c":
        commandStr = opt[1]
    elif opt[0] == "-d":
        debugFileName = opt[1]
    elif opt[0] == "-f":
        following = True
    elif opt[0] == "-k":
        keyFileName = opt[1]
    elif opt[0] == "-m":
        masterMode = True
    elif opt[0] == "-n":
        netInterface = opt[1]
    elif opt[0] == "-o":
        outFileName = opt[1]
    elif opt[0] == "-p":
        sePort = int(opt[1])
    elif opt[0] == "-r":
        recFileName = opt[1]
    elif opt[0] == "-s":
        slaveAddrs = opt[1].split(",")
    elif opt[0] == "-t":
        inputType = opt[1]
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
                debugRaw = True     # -vvvv
    elif opt[0] == "-x":
        haltOnException = True
    else:
        terminate(1, "Unknown option "+opt[0])

# open debug file
if debugFileName != "syslog":
    if debugFileName == "stdout":
        debugFile = sys.stdout
    else:
        debugFile = open(debugFileName, writeMode)

# validate input type
if inputType in ["2", "4"]:
    if not serialDevice:
        terminate(1, "Input device types 2 and 4 are only valid for a serial device")
elif inputType == "n":
    if inFileName != "stdin":
        terminate(1, "Input file cannot be specified for network mode")
    networkDevice = True
    inFileName = "network"
elif inputType != "":
    terminate(1, "Invalid input type "+inputType)
    
# get network interface parameters
if netInterface != "":
    networkDevice = True
    inFileName = "network"
    passiveMode = False
    try:
        netInterfaceParams = netifaces.ifaddresses(netInterface)[2][0]
        ipAddr = netInterfaceParams["addr"]
        broadcastAddr = netInterfaceParams["broadcast"]
        subnetMask = netInterfaceParams["netmask"]
        networkSvcs = True
    except:
        raise
        terminate(1, "network interface is not available")

# serial device validation
if serialDevice:
    following = True
    if inputType == "2":
        passiveMode = False
    elif inputType != "4":
        terminate(1, "Input device type 2 or 4 must be specified for serial device")

# master mode validation
if masterMode:
    passiveMode = False
    if inputType != "4":
        terminate(1, "Master mode only allowed with RS485 serial device")
    if len(slaveAddrs) < 1:
        terminate(1, "At least one slave address must be specified for master mode")

# command mode validation
if commandStr != "":
    commands = parseCommands(commandStr)
    commandAction = True
    passiveMode = False 
    if len(slaveAddrs) != 1:
        terminate(1, "Exactly one slave address must be specified for command mode")

# get encryption key
if keyFileName != "":
    with open(keyFileName) as keyFile:
        keyStr = keyFile.read().rstrip("\n")
    
# print out the arguments and options       
if debugFiles:
    # debug parameters 
    log("debugEnable:", debugEnable)  
    log("debugFiles:", debugFiles)  
    log("debugMsgs:", debugMsgs)
    log("debugData:", debugData)
    log("debugRaw:", debugRaw)
    log("debugFileName:", debugFileName)
    log("haltOnException:", haltOnException)
    # input parameters
    log("inFileName:", inFileName)
    if inputType != "":
        log("inputType:", inputType)
    log("serialDevice:", serialDevice)
    if serialDevice:
        log("    baudRate:", baudRate)
    log("networkDevice:", networkDevice)
    log("sePort:", sePort)
    log("networkSvcs:", networkSvcs)
    if networkSvcs:
        log("netInterface", netInterface)
        log("    ipAddr", ipAddr)
        log("    subnetMask", subnetMask)
        log("    broadcastAddr", broadcastAddr)
    log("following:", following)
    # action parameters
    log("passiveMode:", passiveMode)
    log("commandAction:", commandAction)
    if commandAction:
        for command in commands:
            log("    command:", " ".join(c for c in command))
    log("masterMode:", masterMode)
    if masterMode or commandAction:
        log("slaveAddrs:", ",".join(slaveAddr for slaveAddr in slaveAddrs))
    # output parameters
    log("outFileName:", outFileName)
    if recFileName != "":
        log("recFileName:", recFileName)
    log("append:", writeMode)
    if keyFileName != "":
        log("keyFileName:", keyFileName)
        log("key:", keyStr)
    if updateFileName != "":
        log("updateFileName:", updateFileName)

