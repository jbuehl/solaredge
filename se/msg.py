# SolarEdge message protocol

import struct
import time
import logging
import se.logutils
from Crypto.Cipher import AES
from Crypto.Random import random

logger = logging.getLogger(__name__)

sleepInterval = .1

class SECrypto:
    def __init__(self, key, msg0503):
        """
        Initialise a SolarEdge communication decryption object.

        key:     a 16-byte string which consists of the values of
                 parameters 0239, 023a, 023b, and 023c.
        msg0503: a 34-byte string with the contents of a 0503 message.
        """
        enkey1 = map(ord, AES.new(key).encrypt(msg0503[:16]))
        self.cipher = AES.new("".join(
            map(chr, (enkey1[i] ^ ord(msg0503[i + 16]) for i in range(16)))))
        self.encrypt_seq = random.randint(0, 0xffff)

    def crypt(self, msg003d):
        """
        msg003d: the contents of the 003d message to crypt, as list(int).

        Modifies the list in-place and returns it.
        """
        rand1 = msg003d[:16]
        pos = 16
        while pos < len(msg003d):
            if not pos % 16:
                rand = map(ord, self.cipher.encrypt("".join(map(chr, rand1))))
                for posc in range(15, -1, -1):
                    rand1[posc] = (rand1[posc] + 1) & 0xff
                    if rand1[posc]:
                        break
            msg003d[pos] ^= rand[pos % 16]
            pos += 1
        return msg003d

    def decrypt(self, msg003d):
        """
        msg003d: the contents of the 003d message to decrypt, as string.

        Returns a tuple(int(sequenceNumber), str(data)).
        """
        msg003d = self.crypt(map(ord, msg003d))
        for i in range(len(msg003d) - 22):
            msg003d[i + 22] ^= msg003d[18 + (i & 3)]
        return (msg003d[16] + (msg003d[17] << 8),
                "".join(map(chr, msg003d[22:])))

    def encrypt(self, msg):
        """
        msg: the contents of the data to encrypt, as string.

        Returns the data encrypted.
        """
        self.encrypt_seq = (self.encrypt_seq + 1) & 0xffff
        rand1 = [random.randint(0, 255) for x in range(16)]
        rand2 = [random.randint(0, 255) for x in range(4)]
        seqnr = [self.encrypt_seq & 0xff, self.encrypt_seq >> 8 & 0xff]
        msg003d = rand1 + seqnr + rand2 + map(ord, msg)
        for i in range(len(msg)):
            msg003d[i + 22] ^= msg003d[18 + (i & 3)]
        return "".join(map(chr, self.crypt(msg003d)))


# cryptography object
cipher = None

# message constants
magic = "\x12\x34\x56\x79"
magicLen = len(magic)
msgHdrLen = 16
checksumLen = 2

# message debugging sequence numbers
dataInSeq = 0
dataOutSeq = 0
recSeq = 0

# return the next message
def readMsg(inFile, recFile, mode):
    global dataInSeq, recSeq
    dataInSeq += 1
    msg = ""
    eof = False
    if not (mode.passiveMode or (mode.serialType == 4)):
        # active mode that is not rs485
        # read the magic number and header
        msg = readBytes(inFile, magicLen + msgHdrLen, mode)
        if msg == "":   # end of file
            return (msg, True)
        (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = \
            struct.unpack("<HHHLLH", msg[magicLen:])
        # read the data and checksum
        msg += readBytes(inFile, dataLen + checksumLen, mode)
        msg = msg[magicLen:]    # strip the magic number from the beginning
    else:
        # passive mode or rs485
        # read 1 byte at a time until the next magic number
        while msg[-magicLen:] != magic:
            nextByte = readBytes(inFile, 1, mode)
            if nextByte == "":  # end of file
                eof = True
                msg += magic  # append a magic number to end the loop
            else:
                msg += nextByte
        msg = msg[:-magicLen]  # strip the magic number from the end
    if len(msg) > 0:  # don't log zero length messages
        logger.message("-->", dataInSeq, magic + msg, inFile.name)
    if recFile:
        recSeq += 1
        logger.message("<--", recSeq, magic + msg, recFile.name)
        recFile.write(magic + msg)  # include the magic number in the recorded file
        recFile.flush()
    return (msg, eof)

# return the specified number of bytes
def readBytes(inFile, length, mode):
    try:
        inBuf = inFile.read(length)
        if inBuf == "":  # end of file
            if mode.following:
                # wait for more data
                while inBuf == "":
                    time.sleep(sleepInterval)
                    inBuf = inFile.read(length)
        return inBuf
    # treat exceptions as end of file
    except Exception as ex:
        logger.info("Exception:", exc_info=ex)
        return ""

# parse a message
def parseMsg(msg, keyStr=""):
    global cipher
    if len(msg) < msgHdrLen + checksumLen:  # throw out messages that are too short
        return (0, 0, 0, 0, "")
    else:
        (msgSeq, fromAddr, toAddr, function, data) = validateMsg(msg)
        # encryption key
        if function == 0x0503:
            if keyStr:
                logger.data("Creating cipher object with key", keyStr)
                cipher = SECrypto(keyStr.decode("hex"), data)
            return (msgSeq, fromAddr, toAddr, function, "")
        # encrypted message
        elif function == 0x003d:
            if cipher:
                # decrypt the data and validate that as a message
                logger.data("Decrypting message")
                (seq, dataMsg) = cipher.decrypt(data)
                (msgSeq, fromAddr, toAddr, function, data) = validateMsg(dataMsg[4:])
            else:  # don't have a key yet
                logger.data("Decryption key not yet available")
                return (0, 0, 0, 0, "")
        return (msgSeq, fromAddr, toAddr, function, data)

# parse the header and validate the message
def validateMsg(msg):
    # message must be at least a header and checksum
    if len(msg) < msgHdrLen + checksumLen:
        logger.error("Message too short")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, "")
    # parse the message header
    (dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function) = struct.unpack("<HHHLLH", msg[0:msgHdrLen])
    logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function)
    # header + data + checksum can't be longer than the message
    if msgHdrLen + dataLen + checksumLen > len(msg):
        logger.error("Data length is too big for the message")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, "")
    # data length must match inverse length
    if dataLen != ~dataLenInv & 0xffff:
        logger.error("Data length doesn't match inverse length")
        for l in se.logutils.format_data(msg):
            logger.data(l)
        return (0, 0, 0, 0, "")
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
        return (0, 0, 0, 0, "")
    return (msgSeq, fromAddr, toAddr, function, data)

# format a message
def formatMsg(msgSeq, fromAddr, toAddr, function, data="", encrypt=True):
    checksum = calcCrc(struct.pack(">HLLH", msgSeq, fromAddr, toAddr, function) + data)
    msg = struct.pack("<HHHLLH", len(data), ~len(data) & 0xffff, msgSeq,
                      fromAddr, toAddr, function) + data + struct.pack("<H", checksum)
    logMsgHdr(len(data), ~len(data) & 0xffff, msgSeq, fromAddr, toAddr, function)

    if cipher and encrypt:
        # encrypt the data and format that as a message
        logger.data("Encrypting message")
        msg = formatMsg((cipher.encrypt_seq+1000) & 0xffff,
            0xfffffffd, 0xffffffff, 0x003d, cipher.encrypt(magic + msg), False)
    return msg

# send a message
def sendMsg(dataFile, msg, recFile):
    global dataOutSeq, recSeq
    dataOutSeq += 1
    logger.message("<--", dataOutSeq, magic + msg, dataFile.name)
    dataFile.write(magic + msg)
    dataFile.flush()
    if recFile:
        recSeq += 1
        logger.message("<--", recSeq, magic + msg, recFile.name)
        recFile.write(magic + msg)
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
        crc = crcTable[(crc ^ ord(d)) & 0xff] ^ (crc >> 8)
    return crc

# formatted print a message header
def logMsgHdr(dataLen, dataLenInv, msgSeq, fromAddr, toAddr, function):
    logger.data("dataLen:    %04x", dataLen)
    logger.data("dataLenInv: %04x", dataLenInv)
    logger.data("sequence:   %04x", msgSeq)
    logger.data("source:     %08x", fromAddr)
    logger.data("dest:       %08x", toAddr)
    logger.data("function:   %04x", function)
