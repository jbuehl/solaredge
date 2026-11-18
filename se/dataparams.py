"""
SolarEdge performance data parameters.

Layouts of the data of each device type, and their item names.
"""

# event data interpretation
# (the item of devData, by index, and what it means)
#
#    0  timeStamp
#    1  Type: 0 or 1
#    2  timeStamp: event start time
#    3  timeStamp: event end time (Type == 0) or tzOffset (Type == 1)
#    4  timeStamp: 0 (Type == 0) or event end time (Type == 1)
#    5  data5: 0
#    6  data6: 0

# format string used to unpack input data
EVENT_IN_FMT = "<LLLlLLL"
# length of data that will be unpacked
EVENT_IN_FMT_LEN = (len(EVENT_IN_FMT) - 1) * 4
# mapping of input data to device data items
EVENT_IDX = [0, 1, 2, 3, 4]
# device data item names
EVENT_ITEMS = ["Date", "Time", "ID", "Type", "Event1", "Event2", "Event3"]

# inverter data interpretation
# (the item of devData, by index, and what it means)
#
#    0  timeStamp
#    1  Uptime: uptime (s) ?
#    2  Interval: time in last interval (s) ?
#    3  Temp: temperature (°C)
#    4  Eday: energy produced today (Wh)
#    5  Eac: energy produced in last interval (Wh)
#    6  Vac: AC volts
#    7  Iac: AC current
#    8  freq: frequency (Hz)
#    9  data9: 0xff7fffff
#   10  data10: 0xff7fffff
#   11  Vdc: DC volts
#   12  data12: 0xff7fffff
#   13  Etot: total energy produced (Wh)
#   14  data14: ?
#   15  data15: 0xff7fffff
#   16  data16: 0.0
#   17  data17: 0.0
#   18  Pmax: max power (W) = 5000
#   19  data19: 0.0
#   20  data20: ?
#   21  data21: 0xff7fffff
#   22  data22: 0xff7fffff
#   23  Pac: AC power (W)
#   24  data24: ?
#   25  data25: 0xff7fffff

# format string used to unpack input data
INV_IN_FMT = "<LLLffffffLLfLffLfffffLLffL"
# length of data that will be unpacked
INV_IN_FMT_LEN = (len(INV_IN_FMT) - 1) * 4
# mapping of input data to device data items
INV_IDX = [0, 1, 2, 3, 4, 5, 6, 7, 8, 11, 13, 18, 23]
# device data item names
INV_ITEMS = [
    "Date",
    "Time",
    "ID",
    "Uptime",
    "Interval",
    "Temp",
    "Eday",
    "Eac",
    "Vac",
    "Iac",
    "Freq",
    "Vdc",
    "Etot",
    "Pmax",
    "Pac",
]
# device data output file format strings
INV_OUT_FMT = [
    "%s",
    "%s",
    "%s",
    "%d",
    "%d",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
]

# 3 phase inverter data interpretation
# (the item of devData, by index, and what it means)
#
#    0  timeStamp
#    1  Uptime: uptime (s)
#    2  Interval: time in last interval (s)
#    3  Temp: temperature (°C)
#    4  Eday: energy produced today (Wh)
#    5  Eac: energy produced in last interval (Wh)
#    6  Vac1: AC volts
#    7  Vac2: AC volts
#    8  Vac3: AC volts
#    9  Iac1: AC current
#   10  Iac2: AC current
#   11  Iac3: AC current
#   12  freq1: frequency (Hz)
#   13  freq2: frequency (Hz)
#   14  freq3: frequency (Hz)
#   15  EdayDC: Same as Eday, but measured at DC side. Obfuscated by SE because it would directly reveal inverter
#       efficiency.
#   16  Edc: Same as Eac, but measured at DC side. Obfuscated by SE just like EdayDC.
#   17  Vdc: DC volts
#   18  Idc: Same as Iac, but at DC side. Obfuscated by SE.
#   19  Etot: total energy produced (Wh)
#   20  Irdc: What's this?
#   21  data21: 0xff7fffff
#   22  data22: 0.0
#   23  data23: 0.0
#   24  CosPhi1: cos φ, phase 1
#   25  CosPhi2: cos φ, phase 2
#   26  CosPhi3: cos φ, phase 3
#   27  mode: Mode (1=OFF, 2=SLEEPING, 3=STARTING, 4=MPPT, 6=SHUTTING_DOWN, 8=STANDBY)
#   28  GndFrR: Ground Fault Resistance, a float value
#   29  data29: Is this Power Limit in percent? Always 100 or 0
#   30  IoutDC: This is what SolarEdge calls it.
#   31  data31: 0xff7fffff

# format string used to unpack input data
INV_3PH_IN_FMT = "<LLLffffffffffffLLfLffLLLfffLfffL"
# length of data that will be unpacked
INV_3PH_IN_FMT_LEN = (len(INV_3PH_IN_FMT) - 1) * 4
# mapping of input data to device data items
INV_3PH_IDX = [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
]
# device data item names
INV_3PH_ITEMS = [
    "Date",
    "Time",
    "ID",
    "Uptime",
    "Interval",
    "Temp",
    "Eday",
    "Eac",
    "Vac1",
    "Vac2",
    "Vac3",
    "Iac1",
    "Iac2",
    "Iac3",
    "Freq1",
    "Freq2",
    "Freq3",
    "EdayDC",
    "Edc",
    "Vdc",
    "Idc",
    "Etot",
    "Irdc",
    "data21",
    "data22",
    "data23",
    "CosPhi1",
    "CosPhi2",
    "CosPhi3",
    "mode",
    "GndFrR",
    "data29",
    "IoutDC",
    "data31",
]
# device data output file format strings
INV_3PH_OUT_FMT = [
    "%s",
    "%s",
    "%s",
    "%d",
    "%d",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%f",
    "%d",
    "%d",
    "%f",
    "%d",
    "%f",
    "%f",
    "%d",
    "%d",
    "%d",
    "%f",
    "%f",
    "%f",
    "%d",
    "%f",
    "%f",
    "%f",
    "%d",
]

# optimizer data interpretation
# (the item of devData, by index, and what it means)
#
#    0  timeStamp
#    1  inverter: the value & 0xff7fffff
#    3  Uptime: uptime (s) ?
#    4  Vmod: module voltage
#    5  Vopt: optimizer voltage
#    6  Imod: module current
#    7  Eday: energy produced today (Wh)
#    8  Temp: temperature (°C)

# format string used to unpack input data
OPT_IN_FMT = "<LLLLfffff"
# length of data that will be unpacked
OPT_IN_FMT_LEN = (len(OPT_IN_FMT) - 1) * 4
# mapping of input data to device data items
OPT_IDX = [0, 1, 3, 4, 5, 6, 7, 8]
# device data item names
OPT_ITEMS = [
    "Date",
    "Time",
    "ID",
    "Inverter",
    "Uptime",
    "Vmod",
    "Vopt",
    "Imod",
    "Eday",
    "Temp",
]
# device data output file format strings
OPT_OUT_FMT = ["%s", "%s", "%s", "%s", "%d", "%f", "%f", "%f", "%f", "%f"]

# Decode optimizer data in packet type 0x0080
#  (into same order as original data)
#
# Byte index (in reverse order):
#
# 0c 0b 0a 09 08 07 06 05 04 03 02 01 00
# Tt Ee ee Cc cO o# pp Uu uu Dd dd dd dd
#  # = oo|Pp
#
#  Temp, 8 bit (1.6 °C)  Signed?, 1.6 is best guess at factor
#  Energy in day, 16 bit (1/4 Wh)
#  Current (panel), 12 bit (1/160 A)
#  Voltage output, 10 bit (1/8 V)
#  Voltage panel, 10 bit (1/8 V)
#  Uptime of optimizer, 16 bit (s)
#  DateTime, 32 bit (s)

# Decode optimizer data in packet type 0x0082
#  (into same order as original data)
#
# Byte index (in reverse order):
#
# 0e 0d 0c 0b 0a 09 08 07 06 05 04 03 02 01 00
# ?? ?? ?? ?? ?? Cc cO o# pp Uu uu Dd dd dd dd
#  # = oo|Pp
#  ?? ?? ?? ?? ?? always contain the same bytes
#
#  Current (panel), 12 bit (1/160 A)
#  voltage Output, 10 bit (1/8 V)
#  voltage Panel, 10 bit (1/8 V)
#  Uptime of optimizer, 16 bit (s)
#  DateTime, 32 bit (s)
#
