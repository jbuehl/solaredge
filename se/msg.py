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

sleepInterval = 0.1

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
        # active mode that is not RS485
        # read the magic number and header
        msg = readBytes(inFile, recFile, magicLen + msgHdrLen, mode, state)
        if not msg:  # end of file
            return (msg, True)
        (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = (
            struct.unpack("<HHHLLH", msg[magicLen:])
        )
        # read the data and checksum
        msg += readBytes(inFile, recFile, dataLen + checksumLen, mode, state)
        msg = msg[magicLen:]  # strip the magic number from the beginning
    else:
        # passive mode or RS485
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
        se.logutils.setState(
            state, "lastByteRead", "{:02x}".format(bytearray(inBuf)[-1])
        )
        return inBuf
    # treat exceptions as end of file
    except Exception as ex:
        logger.info("Exception while reading data: " + str(ex))
        return b""


# parse a message
def parseMsg(msg):
    if (
        len(msg) < msgHdrLen + checksumLen
    ):  # throw out messages that are too short
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
    (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = struct.unpack(
        "<HHHLLH", msg[0:msgHdrLen]
    )
    logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function)
    # header + data + checksum can't be longer than the message
    if msgHdrLen + dataLen + checksumLen > len(msg):
        logger.error("Data length is too big for the message")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    # data length must match inverse length
    if dataLen != ~dataLenInv & 0xFFFF:
        logger.error("Data length doesn't match inverse length")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    data = msg[msgHdrLen : msgHdrLen + dataLen]
    # discard extra bytes after the message
    extraLen = len(msg) - (msgHdrLen + dataLen + checksumLen)
    if extraLen != 0:
        logger.data("Discarding %s extra bytes", extraLen)
        for l in se.logutils.format_data(msg[-extraLen:]):
            logger.data(l)
    # validate the checksum
    checksum = struct.unpack(
        "<H", msg[msgHdrLen + dataLen : msgHdrLen + dataLen + checksumLen]
    )[0]
    calcsum = calcCrc(
        struct.pack(">HLLH", msgSeq, fromAddr, toAddr, function) + data
    )
    if calcsum != checksum:
        logger.error(
            "Checksum error. Expected 0x%04x, got 0x%04x" % (checksum, calcsum)
        )
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, b"")
    return (msgSeq, fromAddr, toAddr, function, data)


# format a message
def formatMsg(msgSeq, fromAddr, toAddr, function, data=b"", encrypt=True):
    checksum = calcCrc(
        bytearray(struct.pack(">HLLH", msgSeq, fromAddr, toAddr, function))
        + data
    )
    msg = bytearray(
        struct.pack(
            "<HHHLLH",
            len(data),
            ~len(data) & 0xFFFF,
            msgSeq,
            fromAddr,
            toAddr,
            function,
        )
        + data
        + struct.pack("<H", checksum)
    )
    logMsgHdr(
        len(data), ~len(data) & 0xFFFF, msgSeq, fromAddr, toAddr, function
    )
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


# CRC calculation
#
# CRC-16 with the following parameters:
#
# width=16 poly=0x8005 init=0x5a5a refin=true refout=true xorout=0x0000

crcTable = [
    0x0000,
    0xC0C1,
    0xC181,
    0x0140,
    0xC301,
    0x03C0,
    0x0280,
    0xC241,
    0xC601,
    0x06C0,
    0x0780,
    0xC741,
    0x0500,
    0xC5C1,
    0xC481,
    0x0440,
    0xCC01,
    0x0CC0,
    0x0D80,
    0xCD41,
    0x0F00,
    0xCFC1,
    0xCE81,
    0x0E40,
    0x0A00,
    0xCAC1,
    0xCB81,
    0x0B40,
    0xC901,
    0x09C0,
    0x0880,
    0xC841,
    0xD801,
    0x18C0,
    0x1980,
    0xD941,
    0x1B00,
    0xDBC1,
    0xDA81,
    0x1A40,
    0x1E00,
    0xDEC1,
    0xDF81,
    0x1F40,
    0xDD01,
    0x1DC0,
    0x1C80,
    0xDC41,
    0x1400,
    0xD4C1,
    0xD581,
    0x1540,
    0xD701,
    0x17C0,
    0x1680,
    0xD641,
    0xD201,
    0x12C0,
    0x1380,
    0xD341,
    0x1100,
    0xD1C1,
    0xD081,
    0x1040,
    0xF001,
    0x30C0,
    0x3180,
    0xF141,
    0x3300,
    0xF3C1,
    0xF281,
    0x3240,
    0x3600,
    0xF6C1,
    0xF781,
    0x3740,
    0xF501,
    0x35C0,
    0x3480,
    0xF441,
    0x3C00,
    0xFCC1,
    0xFD81,
    0x3D40,
    0xFF01,
    0x3FC0,
    0x3E80,
    0xFE41,
    0xFA01,
    0x3AC0,
    0x3B80,
    0xFB41,
    0x3900,
    0xF9C1,
    0xF881,
    0x3840,
    0x2800,
    0xE8C1,
    0xE981,
    0x2940,
    0xEB01,
    0x2BC0,
    0x2A80,
    0xEA41,
    0xEE01,
    0x2EC0,
    0x2F80,
    0xEF41,
    0x2D00,
    0xEDC1,
    0xEC81,
    0x2C40,
    0xE401,
    0x24C0,
    0x2580,
    0xE541,
    0x2700,
    0xE7C1,
    0xE681,
    0x2640,
    0x2200,
    0xE2C1,
    0xE381,
    0x2340,
    0xE101,
    0x21C0,
    0x2080,
    0xE041,
    0xA001,
    0x60C0,
    0x6180,
    0xA141,
    0x6300,
    0xA3C1,
    0xA281,
    0x6240,
    0x6600,
    0xA6C1,
    0xA781,
    0x6740,
    0xA501,
    0x65C0,
    0x6480,
    0xA441,
    0x6C00,
    0xACC1,
    0xAD81,
    0x6D40,
    0xAF01,
    0x6FC0,
    0x6E80,
    0xAE41,
    0xAA01,
    0x6AC0,
    0x6B80,
    0xAB41,
    0x6900,
    0xA9C1,
    0xA881,
    0x6840,
    0x7800,
    0xB8C1,
    0xB981,
    0x7940,
    0xBB01,
    0x7BC0,
    0x7A80,
    0xBA41,
    0xBE01,
    0x7EC0,
    0x7F80,
    0xBF41,
    0x7D00,
    0xBDC1,
    0xBC81,
    0x7C40,
    0xB401,
    0x74C0,
    0x7580,
    0xB541,
    0x7700,
    0xB7C1,
    0xB681,
    0x7640,
    0x7200,
    0xB2C1,
    0xB381,
    0x7340,
    0xB101,
    0x71C0,
    0x7080,
    0xB041,
    0x5000,
    0x90C1,
    0x9181,
    0x5140,
    0x9301,
    0x53C0,
    0x5280,
    0x9241,
    0x9601,
    0x56C0,
    0x5780,
    0x9741,
    0x5500,
    0x95C1,
    0x9481,
    0x5440,
    0x9C01,
    0x5CC0,
    0x5D80,
    0x9D41,
    0x5F00,
    0x9FC1,
    0x9E81,
    0x5E40,
    0x5A00,
    0x9AC1,
    0x9B81,
    0x5B40,
    0x9901,
    0x59C0,
    0x5880,
    0x9841,
    0x8801,
    0x48C0,
    0x4980,
    0x8941,
    0x4B00,
    0x8BC1,
    0x8A81,
    0x4A40,
    0x4E00,
    0x8EC1,
    0x8F81,
    0x4F40,
    0x8D01,
    0x4DC0,
    0x4C80,
    0x8C41,
    0x4400,
    0x84C1,
    0x8581,
    0x4540,
    0x8701,
    0x47C0,
    0x4680,
    0x8641,
    0x8201,
    0x42C0,
    0x4380,
    0x8341,
    0x4100,
    0x81C1,
    0x8081,
    0x4040,
]


def calcCrc(data):
    crc = 0x5A5A  # initial value
    for d in data:
        crc = crcTable[(crc ^ d) & 0xFF] ^ (crc >> 8)
    return crc


# print a formatted message header
def logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function):
    logger.data("dataLen:    %04x", dataLen)
    logger.data("dataLenInv: %04x", dataLenInv)
    logger.data("sequence:   %04x", msgSeq)
    logger.data("source:     %08x", fromAddr)
    logger.data("dest:       %08x", toAddr)
    logger.data("function:   %04x", function)
