# SolarEdge performance data parameters

# event data interpretation
#
#   timeStamp = devData[0]
#   Type = devData[1] # 0 or 1
#   timeStamp = devData[2] # event start time
#   timeStamp = devData[3] # event end time (Type == 0) or tzOffset (Type == 1)
#   timeStamp = devData[4] # 0 (Type == 0) or event end time (Type == 1)
#   data5 = devData[5] # 0
#   data6 = devData[6] # 0

# format string used to unpack input data
eventInFmt = "<LLLlLLL"
# length of data that will be unpacked
eventInFmtLen = (len(eventInFmt)-1)*4
# mapping of input data to device data items
eventIdx = [0,1,2,3,4]
# device data item names
eventItems = ["Date", "Time", "ID", "Type", "Event1", "Event2", "Event3"]

# inverter data interpretation
#
#   timeStamp = devData[0]
#   Uptime = devData[1] # uptime (secs) ?
#   Interval = devData[2] # time in last interval (secs) ?
#   Temp = devData[3] # temperature (C)
#   Eday = devData[4] # energy produced today (Wh)
#   Eac = devData[5] # energy produced in last interval (Wh)
#   Vac = devData[6] # AC volts
#   Iac = devData[7] # AC current
#   freq = devData[8] # frequency (Hz)
#   data9 = devData[9] # 0xff7fffff
#   data10 = devData[10] # 0xff7fffff
#   Vdc = devData[11] # DC volts
#   data12 = devData[12] # 0xff7fffff
#   Etot = devData[13] # total energy produced (Wh)
#   data14 = devData[14] # ?
#   data15 = devData[15] # 0xff7fffff
#   data16 = devData[16] # 0.0
#   data17 = devData[17] # 0.0
#   Pmax = devData[18] # max power (W) = 5000
#   data19 = devData[19] # 0.0
#   data20 = devData[20] # ?
#   data21 = devData[21] # 0xff7fffff
#   data22 = devData[22] # 0xff7fffff
#   Pac = devData[23] # AC power (W)
#   data24 = devData[24] # ?
#   data25 = devData[25] # 0xff7fffff
    
# format string used to unpack input data
invInFmt = "<LLLffffffLLfLffLfffffLLffL"
# length of data that will be unpacked
invInFmtLen = (len(invInFmt)-1)*4
# mapping of input data to device data items
invIdx = [0,1,2,3,4,5,6,7,8,11,13,18,23]
# device data item names
invItems = ["Date", "Time", "ID", "Uptime", "Interval", "Temp",
            "Eday", "Eac", "Vac", "Iac", "Freq", "Vdc",
            "Etot", "Pmax", "Pac"]
# device data output file format strings
invOutFmt = ["%s", "%s", "%s", "%d", "%d", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f"]

# optimizer data interpretation
#
#   timeStamp = devData[0]
#   inverter = devData[1] & 0xff7fffff
#   Uptime = devData[3] # uptime (secs) ?
#   Vmod = devData[4] # module voltage
#   Vopt = devData[5] # optimizer voltage
#   Imod = devData[6] # module current
#   Eday = devData[7] # energy produced today (Wh)
#   Temp = devData[8] # temperature (C)

# format string used to unpack input data
optInFmt = "<LLLLfffff"
# length of data that will be unpacked
optInFmtLen = (len(optInFmt)-1)*4
# mapping of input data to device data items
optIdx = [0,1,3,4,5,6,7,8]
# device data item names
optItems = ["Date", "Time", "ID", "Inverter", "Uptime",
            "Vmod", "Vopt", "Imod", "Eday", "Temp"]
# device data output file format strings
optOutFmt = ["%s", "%s", "%s", "%s", "%d", "%f", "%f", "%f", "%f", "%f"]

# Decode optimiser data in packet type 0x0080
#  (into same order as original data)
#
# Byte index (in reverse order):
# 
# 0c 0b 0a 09 08 07 06 05 04 03 02 01 00
# Tt Ee ee Cc cO o# pp Uu uu Dd dd dd dd 
#  # = oo|Pp
#
#  Temp, 8bit (1.6 degC)  Signed?, 1.6 is best guess at factor
#  Energy in day, 16bit (1/4 Wh)
#  Current (panel), 12 bit (1/160 Amp)
#  voltage Output, 10 bit (1/8 v)
#  voltage Panel, 10 bit (1/8 v)
#  Uptime of optimiser, 16 bit (secs)
#  DateTime, 32 bit (secs)
#

