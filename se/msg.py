# SolarEdge message protocol

import struct
import os
import time
import logging
import datetime
import se.logutils
import binascii
from builtins import bytes

logger = logging.getLogger(__name__)

sleepInterval = .1

# message constants
magic = b"\x12\x34\x56\x79"
magicLen = len(magic)
msgHdrLen = 16
checksumLen = 2

# message debugging sequence numbers
dataInSeq = 0
dataOutSeq = 0

# return the next message
def readMsg(inFile, recFile, mode, state):
    se.logutils.setState(state, "passiveMode", mode.passiveMode)
    se.logutils.setState(state, "serialType", mode.serialType)
    global dataInSeq
    dataInSeq += 1
    msg = b""
    eof = False
    if not mode.passiveMode and (mode.serialType != "4"):
        # active mode that is not rs485
        # read the magic number and header
        msg = readBytes(inFile, recFile, magicLen + msgHdrLen, mode, state)
        if not msg:   # end of file
            return (msg, True)
        (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = \
            struct.unpack("<HHHLLH", msg[magicLen:])
        # read the data and checksum
        msg += readBytes(inFile, recFile, dataLen + checksumLen, mode, state)
        msg = msg[magicLen:]    # strip the magic number from the beginning
    else:
        # passive mode or rs485
        # read 1 byte at a time until the next magic number
        while msg[-magicLen:] != magic:
            nextByte = readBytes(inFile, recFile, 1, mode, state)
            if not nextByte:  # end of file
                eof = True
                msg += magic  # append a magic number to end the loop
            else:
                msg += nextByte
        msg = msg[:-magicLen]  # strip the magic number from the end
    if len(msg) > 0:  # don't log zero length messages
        logger.message("-->", dataInSeq, magic + msg, inFile.name)
    return (msg, eof)

# return the specified number of bytes
def readBytes(inFile, recFile, length, mode, state):
    se.logutils.setState(state, "readLength", length)
    try:
        inBuf = bytes(inFile.read(length))
        if not inBuf:  # end of file
            if mode.following:
                # wait for more data
                while not inBuf:
                    time.sleep(sleepInterval)
                    inBuf = inFile.read(length)
        recordMsg(inBuf, recFile)
        se.logutils.setState(state, "lastByteRead", "{:02x}".format(bytearray(inBuf)[-1]))
        return inBuf
    # treat exceptions as end of file
    except Exception as ex:
        logger.info("Exception while reading data: "+str(ex))
        return b""

# parse a message
def parseMsg(msg):
    if len(msg) < msgHdrLen + checksumLen:  # throw out messages that are too short
        logger.data("Threw out a message that was too short")
        return (0, 0, 0, 0, b"")
    else:
        (msgSeq, fromAddr, toAddr, function, data) = validateMsg(msg)
        return (msgSeq, fromAddr, toAddr, function, data)

# parse the header and validate the message
def validateMsg(msg):
    # message must be at least a header and checksum
    if len(msg) < msgHdrLen + checksumLen:
        logger.error("Message too short")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    # parse the message header
    (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = struct.unpack("<HHHLLH", msg[0:msgHdrLen])
    logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function)
    # header + data + checksum can't be longer than the message
    if msgHdrLen + dataLen + checksumLen > len(msg):
        logger.error("Data length is too big for the message")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    # data length must match inverse length
    if dataLen != ~dataLenInv & 0xffff:
        logger.error("Data length doesn't match inverse length")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    data = msg[msgHdrLen:msgHdrLen + dataLen]
    # discard extra bytes after the message
    extraLen = len(msg) - (msgHdrLen + dataLen + checksumLen)
    if extraLen != 0:
        logger.data("Discarding %s extra bytes", extraLen)
        for l in se.logutils.format_data(msg[-extraLen:]):
            logger.data(l)
    # validate the checksum
    checksum = struct.unpack("<H", msg[msgHdrLen + dataLen:msgHdrLen + dataLen + checksumLen])[0]
    calcsum = calcCrc(
        struct.pack(">HLLH", msgSeq, fromAddr, toAddr, function) + data)
    if calcsum != checksum:
        logger.error("Checksum error. Expected 0x%04x, got 0x%04x" % (checksum, calcsum))
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    return (msgSeq, fromAddr, toAddr, function, data)

# format a message
def formatMsg(msgSeq, fromAddr, toAddr, function, data=b"", encrypt=True):
    checksum = calcCrc(bytearray(struct.pack(">HLLH", msgSeq, fromAddr, toAddr, function)) + data)
    msg = bytearray(struct.pack("<HHHLLH", len(data), ~len(data) & 0xffff, msgSeq,
                      fromAddr, toAddr, function) + data + struct.pack("<H", checksum))
    logMsgHdr(len(data), ~len(data) & 0xffff, msgSeq, fromAddr, toAddr, function)
    return msg

# send a message
def sendMsg(dataFile, msg, recFile):
    global dataOutSeq
    dataOutSeq += 1
    logger.message("<--", dataOutSeq, magic + msg, dataFile.name)
    dataFile.write(magic + msg)
    dataFile.flush()
    recordMsg(magic + msg, recFile)

# write a message to the record file
def recordMsg(msg, recFile):
    if recFile:
        recFile.write(msg)
        recFile.flush()

# crc calculation
#
# CRC-16 with the following parameters:
#
# width=16 poly=0x8005 init=0x5a5a refin=true refout=true xorout=0x0000

crcTable = [
    0x0000, 0xc0c1, 0xc181, 0x0140, 0xc301, 0x03c0, 0x0280, 0xc241, 0xc601,
    0x06c0, 0x0780, 0xc741, 0x0500, 0xc5c1, 0xc481, 0x0440, 0xcc01, 0x0cc0,
    0x0d80, 0xcd41, 0x0f00, 0xcfc1, 0xce81, 0x0e40, 0x0a00, 0xcac1, 0xcb81,
    0x0b40, 0xc901, 0x09c0, 0x0880, 0xc841, 0xd801, 0x18c0, 0x1980, 0xd941,
    0x1b00, 0xdbc1, 0xda81, 0x1a40, 0x1e00, 0xdec1, 0xdf81, 0x1f40, 0xdd01,
    0x1dc0, 0x1c80, 0xdc41, 0x1400, 0xd4c1, 0xd581, 0x1540, 0xd701, 0x17c0,
    0x1680, 0xd641, 0xd201, 0x12c0, 0x1380, 0xd341, 0x1100, 0xd1c1, 0xd081,
    0x1040, 0xf001, 0x30c0, 0x3180, 0xf141, 0x3300, 0xf3c1, 0xf281, 0x3240,
    0x3600, 0xf6c1, 0xf781, 0x3740, 0xf501, 0x35c0, 0x3480, 0xf441, 0x3c00,
    0xfcc1, 0xfd81, 0x3d40, 0xff01, 0x3fc0, 0x3e80, 0xfe41, 0xfa01, 0x3ac0,
    0x3b80, 0xfb41, 0x3900, 0xf9c1, 0xf881, 0x3840, 0x2800, 0xe8c1, 0xe981,
    0x2940, 0xeb01, 0x2bc0, 0x2a80, 0xea41, 0xee01, 0x2ec0, 0x2f80, 0xef41,
    0x2d00, 0xedc1, 0xec81, 0x2c40, 0xe401, 0x24c0, 0x2580, 0xe541, 0x2700,
    0xe7c1, 0xe681, 0x2640, 0x2200, 0xe2c1, 0xe381, 0x2340, 0xe101, 0x21c0,
    0x2080, 0xe041, 0xa001, 0x60c0, 0x6180, 0xa141, 0x6300, 0xa3c1, 0xa281,
    0x6240, 0x6600, 0xa6c1, 0xa781, 0x6740, 0xa501, 0x65c0, 0x6480, 0xa441,
    0x6c00, 0xacc1, 0xad81, 0x6d40, 0xaf01, 0x6fc0, 0x6e80, 0xae41, 0xaa01,
    0x6ac0, 0x6b80, 0xab41, 0x6900, 0xa9c1, 0xa881, 0x6840, 0x7800, 0xb8c1,
    0xb981, 0x7940, 0xbb01, 0x7bc0, 0x7a80, 0xba41, 0xbe01, 0x7ec0, 0x7f80,
    0xbf41, 0x7d00, 0xbdc1, 0xbc81, 0x7c40, 0xb401, 0x74c0, 0x7580, 0xb541,
    0x7700, 0xb7c1, 0xb681, 0x7640, 0x7200, 0xb2c1, 0xb381, 0x7340, 0xb101,
    0x71c0, 0x7080, 0xb041, 0x5000, 0x90c1, 0x9181, 0x5140, 0x9301, 0x53c0,
    0x5280, 0x9241, 0x9601, 0x56c0, 0x5780, 0x9741, 0x5500, 0x95c1, 0x9481,
    0x5440, 0x9c01, 0x5cc0, 0x5d80, 0x9d41, 0x5f00, 0x9fc1, 0x9e81, 0x5e40,
    0x5a00, 0x9ac1, 0x9b81, 0x5b40, 0x9901, 0x59c0, 0x5880, 0x9841, 0x8801,
    0x48c0, 0x4980, 0x8941, 0x4b00, 0x8bc1, 0x8a81, 0x4a40, 0x4e00, 0x8ec1,
    0x8f81, 0x4f40, 0x8d01, 0x4dc0, 0x4c80, 0x8c41, 0x4400, 0x84c1, 0x8581,
    0x4540, 0x8701, 0x47c0, 0x4680, 0x8641, 0x8201, 0x42c0, 0x4380, 0x8341,
    0x4100, 0x81c1, 0x8081, 0x4040
]

def calcCrc(data):
    crc = 0x5a5a  # initial value
    for d in data:
        crc = crcTable[(crc ^ d) & 0xff] ^ (crc >> 8)
    return crc

# formatted print a message header
def logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function):
    logger.data("dataLen:    %04x", dataLen)
    logger.data("dataLenInv: %04x", dataLenInv)
    logger.data("sequence:   %04x", msgSeq)
    logger.data("source:     %08x", fromAddr)
    logger.data("dest:       %08x", toAddr)
    logger.data("function:   %04x", function)
