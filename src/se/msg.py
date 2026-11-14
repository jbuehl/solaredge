"""
SolarEdge message protocol.

Reads, parses, formats, validates and sends the framed messages exchanged
with SolarEdge inverters, including their CRC-16 checksums.
"""

import logging
import struct
import time
from typing import NamedTuple

import se.logutils

logger = logging.getLogger(__name__)

SLEEP_INTERVAL = 0.1

# message constants
magic = b"\x12\x34\x56\x79"
MAGIC_LEN = len(magic)
MSG_HDR_LEN = 16
CHECKSUM_LEN = 2


class MsgHdr(NamedTuple):
    """The header of a message."""

    data_len: int
    data_len_inv: int
    msg_seq: int
    from_addr: int
    to_addr: int
    function: int


class Seq:
    """Debugging sequence numbers of the messages read and written."""

    data_in = 0
    data_out = 0


def read_msg(in_file, rec_file, mode, state):
    """
    Read the next message from the input file.

    In active mode (not RS485) the magic number, header, data and checksum
    are read in turn. In passive mode or RS485 bytes are read one at a time
    until the next magic number is found.

    Returns:
        A tuple (msg, eof), where msg is the message without its magic number
        and eof is True when the end of the input was reached.
    """
    se.logutils.set_state(state, "passiveMode", mode.passiveMode)
    se.logutils.set_state(state, "serialType", mode.serialType)
    Seq.data_in += 1
    msg = b""
    eof = False
    if not mode.passiveMode and (mode.serialType != "4"):
        # active mode that is not RS485
        # read the magic number and header
        msg = read_bytes(
            in_file, rec_file, MAGIC_LEN + MSG_HDR_LEN, mode, state
        )
        if not msg:  # end of file
            return (msg, True)
        (data_len, _data_len_inv, _msg_seq, _from_addr, _to_addr, _function) = (
            struct.unpack("<HHHLLH", msg[MAGIC_LEN:])
        )
        # read the data and checksum
        msg += read_bytes(
            in_file, rec_file, data_len + CHECKSUM_LEN, mode, state
        )
        msg = msg[MAGIC_LEN:]  # strip the magic number from the beginning
    else:
        # passive mode or RS485
        # read 1 byte at a time until the next magic number
        while msg[-MAGIC_LEN:] != magic:
            next_byte = read_bytes(in_file, rec_file, 1, mode, state)
            if not next_byte:  # end of file
                eof = True
                msg += magic  # append a magic number to end the loop
            else:
                msg += next_byte
        msg = msg[:-MAGIC_LEN]  # strip the magic number from the end
    if len(msg) > 0:  # don't log zero length messages
        logger.message("-->", Seq.data_in, magic + msg, in_file.name)
    return (msg, eof)


def read_bytes(in_file, rec_file, length, mode, state):
    """
    Read the specified number of bytes from the input file.

    When following a growing file, waits for more data at the end of the
    file. The bytes read are also written to the record file. Read errors are
    treated as end of file.

    Returns:
        The bytes read, or b"" at end of file or on an error.
    """
    se.logutils.set_state(state, "readLength", length)
    try:
        in_buf = bytes(in_file.read(length))
        # at the end of file, wait for more data when following
        if not in_buf and mode.following:
            while not in_buf:
                time.sleep(SLEEP_INTERVAL)
                in_buf = in_file.read(length)
        record_msg(in_buf, rec_file)
        se.logutils.set_state(
            state, "lastByteRead", f"{bytearray(in_buf)[-1]:02x}"
        )
    # treat exceptions as end of file
    except (IndexError, OSError, ValueError) as ex:
        logger.info("Exception while reading data: %s", ex)
        return b""
    else:
        return in_buf


def parse_msg(msg):
    """
    Parse a message into its sequence, addresses, function and data.

    Messages shorter than a header plus checksum are thrown out.

    Returns:
        A tuple (msgSeq, fromAddr, toAddr, function, data). All fields are
        zero and data is empty if the message is rejected.
    """
    if (
        len(msg) < MSG_HDR_LEN + CHECKSUM_LEN
    ):  # throw out messages that are too short
        logger.data("Threw out a message that was too short")
        return (0, 0, 0, 0, b"")
    (msg_seq, from_addr, to_addr, function, data) = validate_msg(msg)
    return (msg_seq, from_addr, to_addr, function, data)


def reject_msg(msg, reason, *args):
    """
    Log why a message is rejected and dump the message data.

    Returns:
        The empty message tuple (0, 0, 0, 0, b"").
    """
    logger.error(reason, *args)
    for line in se.logutils.format_data(msg):
        logger.data(line)
    return (0, 0, 0, 0, b"")


def validate_msg(msg):
    """
    Parse the header of a message and check its lengths and checksum.

    Extra bytes after the message are logged and discarded.

    Returns:
        A tuple (msgSeq, fromAddr, toAddr, function, data), or the rejected
        message tuple from reject_msg if the message is invalid.
    """
    # message must be at least a header and checksum
    if len(msg) < MSG_HDR_LEN + CHECKSUM_LEN:
        return reject_msg(msg, "Message too short")
    # parse the message header
    (data_len, data_len_inv, msg_seq, from_addr, to_addr, function) = (
        struct.unpack("<HHHLLH", msg[0:MSG_HDR_LEN])
    )
    log_msg_hdr(
        MsgHdr(data_len, data_len_inv, msg_seq, from_addr, to_addr, function)
    )
    # header + data + checksum can't be longer than the message
    if MSG_HDR_LEN + data_len + CHECKSUM_LEN > len(msg):
        return reject_msg(msg, "Data length is too big for the message")
    # data length must match inverse length
    if data_len != ~data_len_inv & 0xFFFF:
        return reject_msg(msg, "Data length doesn't match inverse length")
    data = msg[MSG_HDR_LEN : MSG_HDR_LEN + data_len]
    # discard extra bytes after the message
    extra_len = len(msg) - (MSG_HDR_LEN + data_len + CHECKSUM_LEN)
    if extra_len != 0:
        logger.data("Discarding %s extra bytes", extra_len)
        for line in se.logutils.format_data(msg[-extra_len:]):
            logger.data(line)
    # validate the checksum
    checksum = struct.unpack(
        "<H",
        msg[MSG_HDR_LEN + data_len : MSG_HDR_LEN + data_len + CHECKSUM_LEN],
    )[0]
    calcsum = calc_crc(
        struct.pack(">HLLH", msg_seq, from_addr, to_addr, function) + data
    )
    if calcsum != checksum:
        return reject_msg(
            msg,
            "Checksum error. Expected 0x%04x, got 0x%04x",
            checksum,
            calcsum,
        )
    return (msg_seq, from_addr, to_addr, function, data)


def format_msg(msg_seq, from_addr, to_addr, function, data=b""):
    """
    Build a complete message, with its length fields and checksum.

    Returns:
        The message as a bytearray, without the magic number.
    """
    checksum = calc_crc(
        bytearray(struct.pack(">HLLH", msg_seq, from_addr, to_addr, function))
        + data
    )
    msg = bytearray(
        struct.pack(
            "<HHHLLH",
            len(data),
            ~len(data) & 0xFFFF,
            msg_seq,
            from_addr,
            to_addr,
            function,
        )
        + data
        + struct.pack("<H", checksum)
    )
    log_msg_hdr(
        MsgHdr(
            len(data),
            ~len(data) & 0xFFFF,
            msg_seq,
            from_addr,
            to_addr,
            function,
        )
    )
    return msg


def send_msg(data_file, msg, rec_file):
    """Write a message, prefixed with the magic number, to the data file."""
    Seq.data_out += 1
    logger.message("<--", Seq.data_out, magic + msg, data_file.name)
    data_file.write(magic + msg)
    data_file.flush()
    record_msg(magic + msg, rec_file)


def record_msg(msg, rec_file):
    """Write a message to the record file, if one is open."""
    if rec_file:
        rec_file.write(msg)
        rec_file.flush()


# CRC calculation
#
# CRC-16 with the following parameters:
#
# width=16 poly=0x8005 init=0x5a5a refin=true refout=true xorout=0x0000

CRC_TABLE = [
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


def calc_crc(data):
    """Return the CRC-16 checksum of data, using the table above."""
    crc = 0x5A5A  # initial value
    for d in data:
        crc = CRC_TABLE[(crc ^ d) & 0xFF] ^ (crc >> 8)
    return crc


def log_msg_hdr(hdr):
    """Log each field of a message header at the data log level."""
    logger.data("dataLen:    %04x", hdr.data_len)
    logger.data("dataLenInv: %04x", hdr.data_len_inv)
    logger.data("sequence:   %04x", hdr.msg_seq)
    logger.data("source:     %08x", hdr.from_addr)
    logger.data("dest:       %08x", hdr.to_addr)
    logger.data("function:   %04x", hdr.function)
