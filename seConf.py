# SolarEdge configuration, logging, and debugging

import sys
import time
import sys
import socket
import netifaces
import os
import signal
import serial.tools.list_ports
import logging

# debug flags
debugFileName = "stderr"
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

logger = logging.getLogger(__name__)

LOG_LEVEL_MSG = 9
LOG_LEVEL_RAW = 8

# log an incoming or outgoing data message
def logMsg(direction, seq, msg, endPoint=""):
    if direction == "-->":
        logger.log(LOG_LEVEL_MSG, " ")
    logger.log(LOG_LEVEL_MSG, "%s %s message: %s length: %s", endPoint, direction, seq, len(msg))
    for l in format_data(msg):
        logger.log(LOG_LEVEL_RAW, l)
    if direction == "<--":
        logger.log(LOG_LEVEL_MSG, " ")


# program termination
def terminate(code=0, msg=""):
    logger.exception(msg)
    sys.exit(code)


# hex dump data
def format_data(data):
    line_width = 16

    for i in range(0, len(data), line_width):
        yield "data:       " + ' '.join(x.encode('hex') for x in data[i:i+line_width])

