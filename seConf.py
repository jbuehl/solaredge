# SolarEdge configuration, logging, and debugging

try:
    import syslog
except ImportError:
    # Allow for the fact that syslog is not (to my knowledge) available on Windows
    import seWindowsSyslog as syslog
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
dhcpLeaseTime = 24 * 60 * 60  # 1 day
validMacs = [
    "\xb8\x27\xeb",  # Raspberry Pi
    "\x00\x27\x02",  # SolarEdge
]
dnsTtl = 24 * 60 * 60  # 1 day


# log a message
def log(*args):
    message = " ".join(map(str,args))
    if debugFile:
        debugFile.write(
            time.strftime('%b %d %H:%M:%S', time.localtime()) + " " + message +
            "\n")
        debugFile.flush()
    else:
        syslog.syslog(message)


# log a debug message
def debug(*args):
    if debugEnable:  # global debug flag enables debugging
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
            logLine(data[printPtr:printPtr + lineSize])
            printPtr += lineSize
        if printPtr < len(data):
            logLine(data[printPtr:])

