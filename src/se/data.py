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
    EVENT_IDX,
    EVENT_IN_FMT,
    EVENT_ITEMS,
    INV_3PH_IDX,
    INV_3PH_IN_FMT,
    INV_3PH_IN_FMT_LEN,
    INV_3PH_ITEMS,
    INV_IDX,
    INV_IN_FMT,
    INV_IN_FMT_LEN,
    INV_ITEMS,
    OPT_IDX,
    OPT_IN_FMT,
    OPT_IN_FMT_LEN,
    OPT_ITEMS,
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


def parse_data(function, data):
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


def parse_energy_stats(data):
    """Decode the energy statistics: energy today, this month, this year, total, and time."""
    (eday, emon, eyear, etot, time1) = struct.unpack("<ffffL", data[0:20])
    return {
        "Eday": eday,
        "Emon": emon,
        "Eyear": eyear,
        "Etot": etot,
        "Time1": format_date_time(time1),
    }


def parse_param(data):
    """Decode a single 16-bit little-endian parameter."""
    param = struct.unpack("<H", data)[0]
    logger.data("param:     %04x", param)
    return {"param": param}


def parse_version(data):
    """Decode a version as a "major.minor" string with 4-digit parts."""
    (major, minor) = struct.unpack("<HH", data[0:4])
    version = f"{major:04d}.{minor:04d}"
    logger.data("version:    %s", version)
    return {"version": version}


def format_param(param):
    """Pack a 16-bit parameter as little-endian bytes."""
    return struct.pack("<H", param)


def parse_offset_length(data):
    """Decode a 32-bit offset and length, and keep the rest as the data."""
    (offset, length) = struct.unpack("<LL", data[0:8])
    logger.data("offset:   %08x", offset)
    logger.data("length:   %08x", length)
    return {"offset": offset, "length": length, "data": data[8:]}


def parse_long(data):
    """Decode a single 32-bit little-endian parameter."""
    param = struct.unpack("<L", data)[0]
    logger.data("param:     %08x", param)
    return {"param": param}


def format_long(param):
    """Pack a 32-bit parameter as little-endian bytes."""
    return struct.pack("<L", param)


def parse_value_type(data):
    """Decode a 32-bit value followed by a 16-bit type."""
    (value, data_type) = struct.unpack("<LH", data)
    logger.data("value:     %08x", value)
    logger.data("type:      %04x", data_type)
    return {"value": value, "type": data_type}


def format_value_type(value, data_type):
    """Pack a value and a data type as little-endian bytes."""
    return struct.pack("<HL", value, data_type)


def parse_param_value(data):
    """Decode a 16-bit parameter followed by a 32-bit value."""
    (param, value) = struct.unpack("<HL", data)
    logger.data("param:     %04x", param)
    logger.data("value:     %08x", value)
    return {"param": param, "value": value}


def format_param_value(param, value):
    """Pack a 16-bit parameter and a 32-bit value as little-endian bytes."""
    return struct.pack("<HL", param, value)


def parse_time(data):
    """Decode a Unix time and a signed time zone offset in seconds."""
    (time_value, tz_offset) = struct.unpack("<Ll", data)
    logger.data("time:      %s", time.asctime(time.gmtime(time_value)))
    logger.data("tz:        UTC%+d", tz_offset / 60 / 60)
    return {"time": time_value, "tz": tz_offset}


def format_time(time_value, tz_offset):
    """Pack a Unix time and a signed time zone offset as bytes."""
    return struct.pack("<Ll", time_value, tz_offset)


def parse_status(data):
    """
    Log the status data as a hex dump, and return a status of 0.

    The status is not decoded yet, so the result is always 0. It is believed
    to be seven unsigned 16 bit values (struct format "<HHHHHHH").
    """
    for line in se.logutils.format_data(data):
        logger.data(line)
    return {"status": 0}


def parse_device_data(data):
    """
    Parse the devices in the payload of a performance data message.

    Each device has an 8-byte header with its type, ID and length. Inverters,
    optimizers and events are grouped under their own keys. Any other device
    is parsed by ParseDevice and merged into the result.

    Returns:
        A dict with "inverters", "optimizers" and "events" keys, and the
        attributes of any other devices.
    """
    dev_hdr_len = 8
    inv_dict = {}
    opt_dict = {}
    event_dict = {}
    # Add a master dictionary, to store anything parsed by ParseDevice, indexed by the `devType`
    devs_dict = {}

    data_ptr = 0
    while data_ptr < len(data):
        # device header
        (se_type, se_id, dev_len) = struct.unpack(
            "<HLH", data[data_ptr : data_ptr + dev_hdr_len]
        )
        se_id = parse_id(se_id)
        data_ptr += dev_hdr_len
        # device data
        if se_type == DEV_OPTIMIZER:  # optimizer data
            opt_dict[se_id] = parse_opt_data(
                se_id, OPT_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            log_device(
                "optimizer:     ", se_type, se_id, dev_len, opt_dict[se_id]
            )
        elif se_type == DEV_OPTIMIZER_NEW:  # new format optimizer data
            opt_dict[se_id] = parse_new_opt_data(
                se_id, OPT_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            log_device(
                "optimizer:     ", se_type, se_id, dev_len, opt_dict[se_id]
            )
        elif se_type == DEV_OPTIMIZER_S440:  # s440 optimizers
            opt_dict[se_id] = parse_s440_opt_data(
                se_id, OPT_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            log_device(
                "optimizer:     ", se_type, se_id, dev_len, opt_dict[se_id]
            )
        elif se_type == DEV_INVERTER:  # inverter data
            inv_dict[se_id] = parse_inv_data(
                se_id, INV_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            # Correct odd case where SolarEdge inverter sends NaN value in opposite byte order to all other float values
            # i.e. SolarEdge sends b'\xff\xff\x7f\xff' which in little endian format unpacks as -3.402... * 10 ** 38
            # but b'\xff\x7f\xff\xff' unpacks as NaN, which is the "correct" value when this byte pattern is seen.
            if inv_dict[se_id]["Pmax"] < -3 * 10**38:
                inv_dict[se_id]["Pmax"] = float("nan")
            log_device(
                "inverter:     ", se_type, se_id, dev_len, inv_dict[se_id]
            )
        elif se_type == DEV_INVERTER_3PH:  # 3 phase inverter data
            inv_dict[se_id] = parse_inv3_ph_data(
                se_id, INV_3PH_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            log_device(
                "inverter:     ", se_type, se_id, dev_len, inv_dict[se_id]
            )
        elif se_type == DEV_EVENT:  # wake or sleep event
            event_dict[se_id] = parse_event_data(
                se_id, EVENT_ITEMS, data[data_ptr : data_ptr + dev_len]
            )
            log_device(
                "event:         ", se_type, se_id, dev_len, event_dict[se_id]
            )
        else:  # unknown device type, or one that ParseDevice can handle
            # In production you would usually set explorer to False, to prevent excessively long (and mostly useless)
            # parse results for unknown device types.
            parsed_device = ParseDevice(
                data[data_ptr - dev_hdr_len : data_ptr + dev_len],
                explorer=False,
            )
            # Add the new device attributes (wrapped in a dictionary of
            # appropriate identifiers) to the dictionary of devices
            merge_update(devs_dict, parsed_device.wrap_in_ids())
            log_device(
                f"{parsed_device.dev_type}: ",
                se_type,
                se_id,
                dev_len,
                parsed_device.wrap_in_ids(),
            )

        data_ptr += dev_len
    # A bit of a lazy way out, but embed the pre-existing dictionaries into devsDict
    devs_dict["inverters"] = inv_dict
    devs_dict["optimizers"] = opt_dict
    devs_dict["events"] = event_dict

    return devs_dict


# the parser of the data of each function, which are all defined above
DATA_PARSERS = {
    se.commands.PROT_CMD_SERVER_POST_DATA: parse_device_data,
    se.commands.PROT_RESP_POLESTAR_GET_STATUS: parse_status,
    se.commands.PROT_CMD_PARAMS_GET_SINGLE: parse_param,
    se.commands.PROT_CMD_UPGRADE_START: parse_param,
    se.commands.PROT_CMD_MISC_RESET: parse_value_type,
    se.commands.PROT_RESP_PARAMS_SINGLE: parse_value_type,
    se.commands.PROT_RESP_MISC_GET_VER: parse_version,
    se.commands.PROT_CMD_PARAMS_SET_SINGLE: parse_param_value,
    se.commands.PROT_CMD_UPGRADE_WRITE: parse_offset_length,
    se.commands.PROT_RESP_UPGRADE_SIZE: parse_long,
    se.commands.PROT_RESP_MISC_GET_TYPE: parse_param,
    se.commands.PROT_RESP_SERVER_GMT: parse_time,
    se.commands.PROT_RESP_POLESTAR_GET_ENERGY_STATISTICS_STATUS: parse_energy_stats,
}


def parse_event_data(se_id, event_items, dev_data):
    """Decode the data of a wake or sleep event device."""
    # unpack data and map to items
    se_event_data = [
        struct.unpack(EVENT_IN_FMT, dev_data[:INV_IN_FMT_LEN])[i]
        for i in EVENT_IDX
    ]
    se_event_data[2] = format_date_time(se_event_data[2])
    if se_event_data[1] == 0:
        se_event_data[3] = format_date_time(se_event_data[3])
    else:
        se_event_data[4] = format_date_time(se_event_data[4])
    return dev_data_dict(se_id, event_items, se_event_data)


def parse_inv_data(se_id, inv_items, dev_data):
    """Decode the data of a single phase inverter."""
    # unpack data and map to items
    se_inv_data = [
        struct.unpack(INV_IN_FMT, dev_data[:INV_IN_FMT_LEN])[i] for i in INV_IDX
    ]
    return dev_data_dict(se_id, inv_items, se_inv_data)


def parse_inv3_ph_data(se_id, inv_items, dev_data):
    """Decode the data of a three phase inverter."""
    # unpack data and map to items
    se_inv_data = [
        struct.unpack(INV_3PH_IN_FMT, dev_data[:INV_3PH_IN_FMT_LEN])[i]
        for i in INV_3PH_IDX
    ]
    return dev_data_dict(se_id, inv_items, se_inv_data)


def parse_opt_data(se_id, opt_items, dev_data):
    """Decode the data of an optimizer."""
    # unpack data and map to items
    se_opt_data = [
        struct.unpack(OPT_IN_FMT, dev_data[:OPT_IN_FMT_LEN])[i] for i in OPT_IDX
    ]
    se_opt_data[1] = parse_id(se_opt_data[1])
    return dev_data_dict(se_id, opt_items, se_opt_data)


def parse_new_opt_data(se_id, opt_items, dev_data):
    """Decode the data of an optimizer in the newer format."""
    data = bytearray()
    data.extend(dev_data)
    (time_stamp, uptime) = struct.unpack("<LH", dev_data[0:6])
    vpan = 0.125 * (data[6] | (data[7] << 8 & 0x300))
    vopt = 0.125 * (data[7] >> 2 | (data[8] << 6 & 0x3C0))
    imod = 0.00625 * (data[9] << 4 | (data[8] >> 4 & 0xF))
    eday = 0.25 * (data[11] << 8 | data[10])
    temp = 2.0 * struct.unpack("<b", dev_data[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return dev_data_dict(
        se_id, opt_items, [time_stamp, 0, uptime, vpan, vopt, imod, eday, temp]
    )


def parse_s440_opt_data(se_id, opt_items, dev_data):
    """Decode the data of an S440 optimizer, which has no energy or temperature."""
    data = bytearray()
    data.extend(dev_data)
    (time_stamp, uptime) = struct.unpack("<LH", dev_data[0:6])
    vpan = 0.125 * (data[6] | (data[7] << 8 & 0x300))
    vopt = 0.125 * (data[7] >> 2 | (data[8] << 6 & 0x3C0))
    imod = 0.00625 * (data[9] << 4 | (data[8] >> 4 & 0xF))
    # we don't have those fields
    eday = 0
    temp = 0
    # Don't have an inverter ID in the data, substitute 0
    return dev_data_dict(
        se_id, opt_items, [time_stamp, 0, uptime, vpan, vopt, imod, eday, temp]
    )


def dev_data_dict(se_id, item_names, item_values):
    """
    Build the dict of a device's data items.

    The first value is a timestamp, which is split into "Date" and "Time".
    An invalid timestamp gives "invalid" for both.
    """
    dev_dict = {}
    try:
        dev_dict["Date"] = format_date_stamp(item_values[0])
        dev_dict["Time"] = format_time_stamp(item_values[0])
    except (OverflowError, OSError, TypeError, ValueError) as ex:
        logger.info("Invalid timestamp: %s %s", item_values[0], ex)
        dev_dict["Date"] = "invalid"
        dev_dict["Time"] = "invalid"
    dev_dict["ID"] = se_id
    for i in range(3, len(item_names)):
        dev_dict[item_names[i]] = item_values[i - 2]
    return dev_dict


def write_data(msg_dict, out_file):
    """
    Write a message dict to out_file as one line of sorted JSON.

    Nothing is written if out_file is None or empty.
    """
    if out_file:
        Seq.out += 1
        msg = json.dumps(msg_dict, sort_keys=True)
        logger.data(msg)
        out_file.write(msg.encode("latin-1") + b"\n")
        out_file.flush()


def parse_id(se_id):
    """Return a device ID as uppercase hex, without its extra high bit."""
    return ("%x" % (se_id & 0xFF7FFFFF)).upper()


def format_date_stamp(time_stamp):
    """Format a Unix timestamp as a local date, YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(time_stamp))


def format_time_stamp(time_stamp):
    """Format a Unix timestamp as a local time, HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.localtime(time_stamp))


def format_date_time(time_stamp):
    """
    Format a Unix timestamp as a local time string, using asctime.

    Returns the hex of the packed value if the timestamp is out of range,
    and "invalid" for other bad values.
    """
    try:
        return time.asctime(time.localtime(time_stamp))
    except ValueError:
        return "".join(x.encode("hex") for x in struct.pack("<L", time_stamp))
    except (OverflowError, OSError, TypeError) as ex:
        logger.info("Invalid timestamp: %s %s", time_stamp, ex)
        return "invalid"


def log_device(dev_type, se_type, se_id, dev_len, dev_data):
    """Log a header line for a device, then each of its data items."""
    logger.data("%s %s type: %04x len: %04x", dev_type, se_id, se_type, dev_len)
    for k, v in dev_data.items():
        logger.data("    %s : %s", k, v)
