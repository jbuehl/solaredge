# SolarEdge message protocol

import struct
import os
import time
import logging
import datetime
import se.logutils
import binascii
from builtins import bytes
from Crypto.Cipher import AES
from Crypto.Random import random

logger = logging.getLogger(__name__)

sleepInterval = .1

# Hard coded last0503.msg file. os module used to find full path to calling msg.py file, then removes the se part so it's essentially the root of solaredge (where semonitor.py lives)
LAST0503FILE = os.path.dirname(os.path.realpath(__file__)).replace('/'+ __name__.split(".")[0], '') + "/last0503.msg"

class SECrypto:
    def __init__(self, key, msg0503):
        """
        Initialise a SolarEdge communication decryption object.

        key:     a 16-byte string which consists of the values of
                 parameters 0239, 023a, 023b, and 023c.
        msg0503: a 34-byte string with the contents of a 0503 message.
        """
        # Get the current time in human readable form so a human can ready the last0503.msg file and know when it was last updated
        curtime = datetime.datetime.now()
        mystrtime = curtime.strftime("%Y-%m-%d %H:%M:%S")
        # Create a key by encrypting the data from Solar Edge with our key)
        enkey1 = bytes(AES.new(key, AES.MODE_ECB).encrypt(msg0503[:16]))
        # Store the 0503 message in a hex string
        hex_msg0503 = binascii.hexlify(msg0503)
        # Format the line in the last0503.msg file
        # Format is: String Timestamp (for us humans),Epoch in seconds (for easy math),hex encoded previous message
        outstr = mystrtime + "," + str(int(time.time())) + "," + str(hex_msg0503)
        # Write the outstr to the last0503.msg file, clobbering the previous (hence 'w' write mode)
        ko = open(LAST0503FILE, "w")
        ko.write(outstr)
        ko.close()
        # self.cipher is an AES object
        self.cipher = AES.new(bytes(list((enkey1[i] ^ msg0503[i + 16] for i in range(16)))), AES.MODE_ECB)
        self.encrypt_seq = random.randint(0, 0xffff)

    def crypt(self, msg003d):
        """
        msg003d: the contents of the 003d message to crypt, as bytes.

        Returns the new list
        """
        msg003d = list(msg003d)
        rand1 = list(msg003d[:16])
        pos = 16
        while pos < len(msg003d):
            if not pos % 16:
                rand = bytes(self.cipher.encrypt(bytes(rand1)))
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

        Returns a tuple(int(sequenceNumber), bytes(data)).
        """
        msg003d = self.crypt(msg003d)
        for i in range(len(msg003d) - 22):
            msg003d[i + 22] ^= msg003d[18 + (i & 3)]
        return (msg003d[16] + (msg003d[17] << 8), bytes(msg003d[22:]))

    def encrypt(self, msg):
        """
        msg: the contents of the data to encrypt, as string.

        Returns the data encrypted.
        """
        self.encrypt_seq = (self.encrypt_seq + 1) & 0xffff
        rand1 = [random.randint(0, 255) for x in range(16)]
        rand2 = [random.randint(0, 255) for x in range(4)]
        seqnr = [self.encrypt_seq & 0xff, self.encrypt_seq >> 8 & 0xff]
        msg003d = rand1 + seqnr + rand2 + msg
        for i in range(len(msg)):
            msg003d[i + 22] ^= msg003d[18 + (i & 3)]
        return self.crypt(msg003d)

# cryptography object variable and global indicator if the load of last0503.msg was attempted
cipher = None
bcipher = False

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

# A function to attempt to load the the rotating key from the last0503.msg file
def loadRotKey(keyStr):
    global cipher
    mydata = ""
    # First try the file operation, if this doesn't work, no big deal, we just don't load the key, but we do log the attempt
    try:
        ki = open(LAST0503FILE, "r")
        mydata = ki.read()
        ki.close()
    except:
        logger.data("Could not open last0503.msg file, not loading")

    # If the try block doing the file operation was successful, mydata will now not be blank, so we try to operate on it.
    if mydata:
        # These are the variables where we keep the last load time and the last key data
        lastsave = 0
        lastkey = b""
        # We attempt to load the file and split the contents. If this try fails, we assume the file to have been corrupted (manual edit etc) and we give up, not loading the key
        try:
            lastsave = int(mydata.split(",")[1])
            lastkey = mydata.split(",")[2].strip()
        except:
            logger.data("last0503.msg not in proper format - not loading")
        # If we have both a last load time and data in our variables, we assume the try block succeeded and we do some more validation
        if lastsave != 0 and lastkey:
            # First we check the time, if the last load time is more than 24 hours ago, we give up. No point in trying decryption with an old key
            curtime = int(time.time())
            if curtime - lastsave <= 86400: #86400 seconds is 24 hours 60 secs * 60 min * 24 hours
                # Now we check that our key is indeed 68 characters. If it is not we give up and don't load
                if len(lastkey) == 68: # Check to ensure its 68 characters
                    logger.data("Attempting to load data from last0503.msg")
                    # Our last try if this fails, we log an unknown error
                    try:
                        cipher = SECrypto(binascii.unhexlify(keyStr), binascii.unhexlify(lastkey))
                        logger.data("Rotated key from last0503.msg loaded successfully!")
                    except:
                        logger.data("Unknown error in loading rotating key. Not using")
                else:
                    logger.data("Saved rotating key length not correct. Not using")
    else:
        logger.data("No data read from last0503.msg. Not loading")
    # This function, since it works on the global cipher object, always returns true
    # This return basically sets bcipher and tells the application we've already attempted to load the last0503.msg
    # So even if cipher is still None, don't try to load from file again. There's no point. This should resolve itselve the next 0503 message that is loaded/saved
    return True


# parse a message
def parseMsg(msg, keyStr=""):
    global cipher
    global bcipher
    # If bcipher is False then we've not attempted to load the rotating key from the last0503.msg file.
    # Also, we don't want to load from file if for some reason cipher is not None (it shouldn't be if bcipher is False)
    # If bcipher is False and cipher is None, then try to load the rotating key. The result of the "attempt" to load the rotating key is stored in bcipher. The attempt is ALWAYS true
    # The idea here is that we make one attempt to the load the file, and if it works, then cipher is no longer None and we can move on. Else, don't try loading again.
    if bcipher == False and cipher is None:
        bcipher = loadRotKey(keyStr)
    if len(msg) < msgHdrLen + checksumLen:  # throw out messages that are too short
        logger.data("Threw out a message that was too short")
        return (0, 0, 0, 0, b"")
    else:
        (msgSeq, fromAddr, toAddr, function, data) = validateMsg(msg)
        # encryption key
        if function == 0x0503:
            if keyStr:
                logger.data("Creating cipher object with key", keyStr)
                cipher = SECrypto(binascii.unhexlify(keyStr), data)
            return (msgSeq, fromAddr, toAddr, function, b"")
        # encrypted message
        elif function == 0x003d:
            if cipher:
                # decrypt the data and validate that as a message
                logger.data("Decrypting message")
                (seq, dataMsg) = cipher.decrypt(data)
                if dataMsg[0:4] != magic:
                    logger.data("Invalid decryption key - Clearing Cipher")
                    cipher = None
                    return (0, 0, 0, 0, b"")
                else:
                    (msgSeq, fromAddr, toAddr, function, data) = validateMsg(dataMsg[4:])
            else:  # don't have a key yet
                logger.data("Decryption key not yet available")
                return (0, 0, 0, 0, b"")
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

    if cipher and encrypt:
        # encrypt the data and format that as a message
        logger.data("Encrypting message")
        msg = formatMsg((cipher.encrypt_seq+1000) & 0xffff,
            0xfffffffd, 0xffffffff, 0x003d, cipher.encrypt(magic + msg), False)
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
