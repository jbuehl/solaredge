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


LOG_LEVEL_MSG = 9
LOG_LEVEL_RAW = 8

logging.addLevelName(LOG_LEVEL_MSG, 'MESSAGE')
logging.addLevelName(LOG_LEVEL_RAW, 'RAW')

logging.Logger.message = lambda self, message, *args, **kws: self.log(LOG_LEVEL_MSG, message, *args, **kws) 
logging.Logger.raw = lambda self, message, *args, **kws: self.log(LOG_LEVEL_RAW, message, *args, **kws) 

logger = logging.getLogger(__name__)

# log an incoming or outgoing data message
def logMsg(direction, seq, msg, endPoint=""):
    if direction == "-->":
        logger.message(" ")
    logger.message("%s %s message: %s length: %s", endPoint, direction, seq, len(msg))
    for l in format_data(msg):
        logger.raw(l)
    if direction == "<--":
        logger.message(" ")


# program termination
def terminate(code=0, msg=""):
    logger.exception(msg)
    sys.exit(code)


# hex dump data
def format_data(data):
    line_width = 16

    for i in range(0, len(data), line_width):
        yield "data:       " + ' '.join(x.encode('hex') for x in data[i:i+line_width])

