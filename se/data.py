"""
SolarEdge data interpretation.

Turns the payload of each protocol message into Python values, and formats
values back into bytes. Parsed device data is written out as JSON lines.
"""

import codecs
import json
import logging
import struct
import time

import se.commands
import se.logutils
from se.datadevices import ParseDevice, merge_update
from se.dataparams import (
    eventIdx,
    eventInFmt,
    eventItems,
    inv3PhIdx,
    inv3PhInFmt,
    inv3PhInFmtLen,
    inv3PhItems,
    invIdx,
    invInFmt,
    invInFmtLen,
    invItems,
    optIdx,
    optInFmt,
    optInFmtLen,
    optItems,
)

logger = logging.getLogger(__name__)


# the device types in the data of a performance data message
DEV_OPTIMIZER = 0x0000
DEV_INVERTER = 0x0010
DEV_INVERTER_3PH = 0x0011
DEV_OPTIMIZER_NEW = 0x0080
DEV_OPTIMIZER_S440 = 0x0082
DEV_EVENT = 0x0300


class Seq:
    """Debugging sequence number of the messages written."""

    out = 0


# functions with no arguments
NO_ARGUMENTS = frozenset(
    {
        se.commands.PROT_RESP_ACK,
        se.commands.PROT_RESP_NACK,
        se.commands.PROT_CMD_MISC_GET_VER,
        se.commands.PROT_CMD_MISC_GET_TYPE,
        se.commands.PROT_CMD_SERVER_GET_GMT,
        se.commands.PROT_CMD_SERVER_GET_NAME,
        se.commands.PROT_CMD_POLESTAR_GET_STATUS,
        se.commands.PROT_CMD_POLESTAR_MASTER_GRANT,
        se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK,
    }
)


def parseData(function, data):
    """
    Decode the payload of a protocol message.

    Functions without arguments, and functions with no known parser, are
    returned as a hex string of their data. Unknown functions are logged.

    Args:
        function: The function code of the message.
        data: The payload bytes of the message.

    Returns:
        The decoded payload, a dict for most functions, or a hex string.
    """
    if function in NO_ARGUMENTS:
        return "".join(x.encode("hex") for x in data)
    parser = DATA_PARSERS.get(function)
    if parser is not None:
        return parser(data)
    # unknown function type
    logger.info("Unknown function 0x%04x", function)
    return codecs.encode(data, "hex").decode("ascii")


def parseEnergyStats(data):
    """Decode the energy statistics: energy today, this month, this year, total, and time."""
    (Eday, Emon, Eyear, Etot, Time1) = struct.unpack("<ffffL", data[0:20])
    return {
        "Eday": Eday,
        "Emon": Emon,
        "Eyear": Eyear,
        "Etot": Etot,
        "Time1": formatDateTime(Time1),
    }


def parseParam(data):
    """Decode a single 16-bit little-endian parameter."""
    param = struct.unpack("<H", data)[0]
    logger.data("param:     %04x", param)
    return {"param": param}


def parseVersion(data):
    """Decode a version as a "major.minor" string with 4-digit parts."""
    (major, minor) = struct.unpack("<HH", data[0:4])
    version = f"{major:04d}.{minor:04d}"
    logger.data("version:    %s", version)
    return {"version": version}


def formatParam(param):
    """Pack a 16-bit parameter as little-endian bytes."""
    return struct.pack("<H", param)


def parseOffsetLength(data):
    """Decode a 32-bit offset and length, and keep the rest as the data."""
    (offset, length) = struct.unpack("<LL", data[0:8])
    logger.data("offset:   %08x", offset)
    logger.data("length:   %08x", length)
    return {"offset": offset, "length": length, "data": data[8:]}


def parseLong(data):
    """Decode a single 32-bit little-endian parameter."""
    param = struct.unpack("<L", data)[0]
    logger.data("param:     %08x", param)
    return {"param": param}


def formatLong(param):
    """Pack a 32-bit parameter as little-endian bytes."""
    return struct.pack("<L", param)


def parseValueType(data):
    """Decode a 32-bit value followed by a 16-bit type."""
    (value, dataType) = struct.unpack("<LH", data)
    logger.data("value:     %08x", value)
    logger.data("type:      %04x", dataType)
    return {"value": value, "type": dataType}


def formatValueType(value, dataType):
    """Pack a value and a data type as little-endian bytes."""
    return struct.pack("<HL", value, dataType)


def parseParamValue(data):
    """Decode a 16-bit parameter followed by a 32-bit value."""
    (param, value) = struct.unpack("<HL", data)
    logger.data("param:     %04x", param)
    logger.data("value:     %08x", value)
    return {"param": param, "value": value}


def formatParamValue(param, value):
    """Pack a 16-bit parameter and a 32-bit value as little-endian bytes."""
    return struct.pack("<HL", param, value)


def parseTime(data):
    """Decode a Unix time and a signed time zone offset in seconds."""
    (timeValue, tzOffset) = struct.unpack("<Ll", data)
    logger.data("time:      %s", time.asctime(time.gmtime(timeValue)))
    logger.data("tz:        UTC%+d", tzOffset / 60 / 60)
    return {"time": timeValue, "tz": tzOffset}


def formatTime(timeValue, tzOffset):
    """Pack a Unix time and a signed time zone offset as bytes."""
    return struct.pack("<Ll", timeValue, tzOffset)


def parseStatus(data):
    """
    Log the status data as a hex dump, and return a status of 0.

    The status is not decoded yet, so the result is always 0.
    """
    #    if len(data) > 0:
    #        status = struct.unpack("<HHHHHHH", data)
    #        logger.data("status", "%d "*len(status) % status)
    #    return {"status": status}
    for line in se.logutils.format_data(data):
        logger.data(line)
    return {"status": 0}


def parseDeviceData(data):
    """
    Parse the devices in the payload of a performance data message.

    Each device has an 8-byte header with its type, ID and length. Inverters,
    optimizers and events are grouped under their own keys. Any other device
    is parsed by ParseDevice and merged into the result.

    Returns:
        A dict with "inverters", "optimizers" and "events" keys, and the
        attributes of any other devices.
    """
    devHdrLen = 8
    invDict = {}
    optDict = {}
    eventDict = {}
    # Add a master dictionary, to store anything parsed by ParseDevice, indexed by the `devType`
    devsDict = {}

    dataPtr = 0
    while dataPtr < len(data):
        # device header
        (seType, seId, devLen) = struct.unpack(
            "<HLH", data[dataPtr : dataPtr + devHdrLen]
        )
        seId = parseId(seId)
        dataPtr += devHdrLen
        # device data
        if seType == DEV_OPTIMIZER:  # optimizer data
            optDict[seId] = parseOptData(
                seId, optItems, data[dataPtr : dataPtr + devLen]
            )
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId])
        elif seType == DEV_OPTIMIZER_NEW:  # new format optimizer data
            optDict[seId] = parseNewOptData(
                seId, optItems, data[dataPtr : dataPtr + devLen]
            )
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId])
        elif seType == DEV_OPTIMIZER_S440:  # s440 optimizers
            optDict[seId] = parseS440OptData(
                seId, optItems, data[dataPtr : dataPtr + devLen]
            )
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId])
        elif seType == DEV_INVERTER:  # inverter data
            invDict[seId] = parseInvData(
                seId, invItems, data[dataPtr : dataPtr + devLen]
            )
            # Correct odd case where SolarEdge inverter sends NaN value in opposite byte order to all other float values
            # i.e. SolarEdge sends b'\xff\xff\x7f\xff' which in little endian format unpacks as -3.402... * 10 ** 38
            # but b'\xff\x7f\xff\xff' unpacks as NaN, which is the "correct" value when this byte pattern is seen.
            if invDict[seId]["Pmax"] < -3 * 10**38:
                invDict[seId]["Pmax"] = float("nan")
            logDevice("inverter:     ", seType, seId, devLen, invDict[seId])
        elif seType == DEV_INVERTER_3PH:  # 3 phase inverter data
            invDict[seId] = parseInv3PhData(
                seId, inv3PhItems, data[dataPtr : dataPtr + devLen]
            )
            logDevice("inverter:     ", seType, seId, devLen, invDict[seId])
        elif seType == DEV_EVENT:  # wake or sleep event
            eventDict[seId] = parseEventData(
                seId, eventItems, data[dataPtr : dataPtr + devLen]
            )
            logDevice("event:         ", seType, seId, devLen, eventDict[seId])
        else:  # unknown device type, or one that ParseDevice can handle
            # In production you would usually set explorer to False, to prevent excessively long (and mostly useless)
            # parse results for unknown device types.
            parsedDevice = ParseDevice(
                data[dataPtr - devHdrLen : dataPtr + devLen], explorer=False
            )
            # Add the new device attributes (wrapped in a dictionary of
            # appropriate identifiers) to the dictionary of devices
            merge_update(devsDict, parsedDevice.wrap_in_ids())
            logDevice(
                f"{parsedDevice.devType}: ",
                seType,
                seId,
                devLen,
                parsedDevice.wrap_in_ids(),
            )

        dataPtr += devLen
    # A bit of a lazy way out, but embed the pre-existing dictionaries into devsDict
    devsDict["inverters"] = invDict
    devsDict["optimizers"] = optDict
    devsDict["events"] = eventDict

    return devsDict


# the parser of the data of each function, which are all defined above
DATA_PARSERS = {
    se.commands.PROT_CMD_SERVER_POST_DATA: parseDeviceData,
    se.commands.PROT_RESP_POLESTAR_GET_STATUS: parseStatus,
    se.commands.PROT_CMD_PARAMS_GET_SINGLE: parseParam,
    se.commands.PROT_CMD_UPGRADE_START: parseParam,
    se.commands.PROT_CMD_MISC_RESET: parseValueType,
    se.commands.PROT_RESP_PARAMS_SINGLE: parseValueType,
    se.commands.PROT_RESP_MISC_GET_VER: parseVersion,
    se.commands.PROT_CMD_PARAMS_SET_SINGLE: parseParamValue,
    se.commands.PROT_CMD_UPGRADE_WRITE: parseOffsetLength,
    se.commands.PROT_RESP_UPGRADE_SIZE: parseLong,
    se.commands.PROT_RESP_MISC_GET_TYPE: parseParam,
    se.commands.PROT_RESP_SERVER_GMT: parseTime,
    se.commands.PROT_RESP_POLESTAR_GET_ENERGY_STATISTICS_STATUS: parseEnergyStats,
}


def parseEventData(seId, eventItems, devData):
    """Decode the data of a wake or sleep event device."""
    # unpack data and map to items
    seEventData = [
        struct.unpack(eventInFmt, devData[:invInFmtLen])[i] for i in eventIdx
    ]
    seEventData[2] = formatDateTime(seEventData[2])
    if seEventData[1] == 0:
        seEventData[3] = formatDateTime(seEventData[3])
    else:
        seEventData[4] = formatDateTime(seEventData[4])
    return devDataDict(seId, eventItems, seEventData)


def parseInvData(seId, invItems, devData):
    """Decode the data of a single phase inverter."""
    # unpack data and map to items
    seInvData = [
        struct.unpack(invInFmt, devData[:invInFmtLen])[i] for i in invIdx
    ]
    return devDataDict(seId, invItems, seInvData)


def parseInv3PhData(seId, invItems, devData):
    """Decode the data of a three phase inverter."""
    # unpack data and map to items
    seInvData = [
        struct.unpack(inv3PhInFmt, devData[:inv3PhInFmtLen])[i]
        for i in inv3PhIdx
    ]
    return devDataDict(seId, invItems, seInvData)


def parseOptData(seId, optItems, devData):
    """Decode the data of an optimizer."""
    # unpack data and map to items
    seOptData = [
        struct.unpack(optInFmt, devData[:optInFmtLen])[i] for i in optIdx
    ]
    seOptData[1] = parseId(seOptData[1])
    return devDataDict(seId, optItems, seOptData)


def parseNewOptData(seId, optItems, devData):
    """Decode the data of an optimizer in the newer format."""
    data = bytearray()
    data.extend(devData)
    (timeStamp, uptime) = struct.unpack("<LH", devData[0:6])
    vpan = 0.125 * (data[6] | (data[7] << 8 & 0x300))
    vopt = 0.125 * (data[7] >> 2 | (data[8] << 6 & 0x3C0))
    imod = 0.00625 * (data[9] << 4 | (data[8] >> 4 & 0xF))
    eday = 0.25 * (data[11] << 8 | data[10])
    temp = 2.0 * struct.unpack("<b", devData[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return devDataDict(
        seId, optItems, [timeStamp, 0, uptime, vpan, vopt, imod, eday, temp]
    )


def parseS440OptData(seId, optItems, devData):
    """Decode the data of an S440 optimizer, which has no energy or temperature."""
    data = bytearray()
    data.extend(devData)
    (timeStamp, uptime) = struct.unpack("<LH", devData[0:6])
    vpan = 0.125 * (data[6] | (data[7] << 8 & 0x300))
    vopt = 0.125 * (data[7] >> 2 | (data[8] << 6 & 0x3C0))
    imod = 0.00625 * (data[9] << 4 | (data[8] >> 4 & 0xF))
    # we don't have those fields
    eday = 0
    temp = 0
    # Don't have an inverter ID in the data, substitute 0
    return devDataDict(
        seId, optItems, [timeStamp, 0, uptime, vpan, vopt, imod, eday, temp]
    )


def devDataDict(seId, itemNames, itemValues):
    """
    Build the dict of a device's data items.

    The first value is a timestamp, which is split into "Date" and "Time".
    An invalid timestamp gives "invalid" for both.
    """
    devDict = {}
    try:
        devDict["Date"] = formatDateStamp(itemValues[0])
        devDict["Time"] = formatTimeStamp(itemValues[0])
    except (OverflowError, OSError, TypeError, ValueError) as ex:
        logger.info("Invalid timestamp: %s %s", itemValues[0], ex)
        devDict["Date"] = "invalid"
        devDict["Time"] = "invalid"
    devDict["ID"] = seId
    for i in range(3, len(itemNames)):
        devDict[itemNames[i]] = itemValues[i - 2]
    return devDict


def writeData(msgDict, outFile):
    """
    Write a message dict to outFile as one line of sorted JSON.

    Nothing is written if outFile is None or empty.
    """
    if outFile:
        Seq.out += 1
        msg = json.dumps(msgDict, sort_keys=True)
        logger.data(msg)
        outFile.write(msg.encode("latin-1") + b"\n")
        outFile.flush()


def parseId(seId):
    """Return a device ID as uppercase hex, without its extra high bit."""
    return ("%x" % (seId & 0xFF7FFFFF)).upper()


def formatDateStamp(timeStamp):
    """Format a Unix timestamp as a local date, YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))


def formatTimeStamp(timeStamp):
    """Format a Unix timestamp as a local time, HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))


def formatDateTime(timeStamp):
    """
    Format a Unix timestamp as a local time string, using asctime.

    Returns the hex of the packed value if the timestamp is out of range,
    and "invalid" for other bad values.
    """
    try:
        return time.asctime(time.localtime(timeStamp))
    except ValueError:
        return "".join(x.encode("hex") for x in struct.pack("<L", timeStamp))
    except (OverflowError, OSError, TypeError) as ex:
        logger.info("Invalid timestamp: %s %s", timeStamp, ex)
        return "invalid"


def logDevice(devType, seType, seId, devLen, devData):
    """Log a header line for a device, then each of its data items."""
    logger.data("%s %s type: %04x len: %04x", devType, seId, seType, devLen)
    for k, v in devData.items():
        logger.data("    %s : %s", k, v)
