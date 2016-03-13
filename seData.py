# SolarEdge data interpretation

import struct
import json
from seConf import *
from seCommands import *

# file sequence numbers
invSeq = 0
optSeq = 0
jsonSeq = 0

# parse the message data
def parseData(function, data):
    if function == 0:
        # message was too short to be valid
        debug("debugEnable", "Message too short")
        logData(data)
    elif function in [PROT_RESP_ACK, PROT_RESP_NACK, PROT_CMD_MISC_GET_VER, PROT_CMD_MISC_GET_TYPE, PROT_CMD_SERVER_GET_GMT, PROT_CMD_SERVER_GET_NAME, PROT_CMD_POLESTAR_GET_STATUS]:
        # functions with no arguments
        pass
    elif function == PROT_CMD_SERVER_POST_DATA:
        return parseDeviceData(data)
    elif function == PROT_RESP_POLESTAR_GET_STATUS:
        return parseStatus(data)
    elif function in [PROT_CMD_PARAMS_GET_SINGLE, PROT_CMD_UPGRADE_START]:
        return parseParam(data)
    elif function in [PROT_CMD_MISC_RESET, PROT_RESP_PARAMS_SINGLE]:
        return parseValueType(data)
    elif function == PROT_RESP_MISC_GET_VER:
        return parseVersion(data)
    elif function == PROT_CMD_PARAMS_SET_SINGLE:
        return parseParamValue(data)
    elif function == PROT_CMD_UPGRADE_WRITE:
        return parseOffsetLength(data)
    elif function == PROT_RESP_UPGRADE_SIZE:
        return parseLong(data)
    elif function in [PROT_RESP_MISC_GET_TYPE]:
        return parseParam(data)
    elif function == PROT_RESP_SERVER_GMT:
        return parseTime(data)
    elif function in [0x0503, 0x003d]:
        # encrypted messages
        pass
    else:
        # unknown function type
        raise Exception("Unknown function 0x%04x" % function)
    return {}

def parseParam(data):
    param = struct.unpack("<H", data)[0]
    debug("debugData", "param:     ", "%04x" % param)
    return {"param": param}

def parseVersion(data):
    version = "%04d.%04d" % struct.unpack("<HH", data[0:4])
    debug("debugData", "version:    "+version)
    return {"version": version}

def formatParam(param):
    return struct.pack("<H", param)
        
def parseOffsetLength(data):
    (offset, length) = struct.unpack("<LL", data[0:8])
    debug("debugData", "offset:   ", "%08x" % (offset))
    debug("debugData", "length:   ", "%08x" % (length))
    return {"offset": offset, "length": length, "data": data[8:]}

def parseLong(data):
    param = struct.unpack("<L", data)[0]
    debug("debugData", "param:     ", "%08x" % param)
    return {"param": param}

def formatLong(param):
    return struct.pack("<L", param)
        
def parseValueType(data):
    (value, dataType) = struct.unpack("<LH", data)
    debug("debugData", "value:     ", "%08x" % value)
    debug("debugData", "type:      ", "%04x" % dataType)
    return {"value": value, "type": dataType}

def formatValueType(value, dataType):
    return struct.pack("<HL", value, dataType) 
           
def parseParamValue(data):
    (param, value) = struct.unpack("<HL", data)
    debug("debugData", "param:     ", "%04x" % param)
    debug("debugData", "value:     ", "%08x" % value)
    return {"param": param, "value": value}

def formatParamValue(param, value):
    return struct.pack("<HL", param, value)
    
def parseTime(data):
    (timeValue, tzOffset) = struct.unpack("<Ll", data)
    debug("debugData", "time:      ", time.asctime(time.gmtime(timeValue)))
    debug("debugData", "tz:        ", "UTC%+d" % (tzOffset/60/60))
    return {"time": timeValue, "tz": tzOffset}

def formatTime(timeValue, tzOffset):
    return struct.pack("<Ll", timeValue, tzOffset)
    
# parse status data
def parseStatus(data):
    if len(data) > 0:
        status = struct.unpack("<HHHHHHH", data)
        debug("debugData", "status", "%d "*len(status) % status)
    return {"status": status}

# parse device data
def parseDeviceData(data):
    devHdrLen = 8
    invDict = {}
    optDict = {}
    eventDict = {}
    dataPtr = 0
    while dataPtr < len(data):
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", data[dataPtr:dataPtr+devHdrLen])
        seId = parseId(seId)
        dataPtr += devHdrLen
        # device data
        if seType == 0x0000:    # optimizer data
            optDict[seId] = parseOptData(seId, optItems, data[dataPtr:dataPtr+devLen])
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId], optItems)
        elif seType == 0x0080:  # new format optimizer data
            optDict[seId] = parseNewOptData(seId, optItems, data[dataPtr:dataPtr+devLen])
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId], optItems)
        elif seType == 0x0010:  # inverter data
            invDict[seId] = parseInvData(seId, invItems, data[dataPtr:dataPtr+devLen])
            logDevice("inverter:     ", seType, seId, devLen, invDict[seId], invItems)
        elif seType == 0x0300:  # wake or sleep event
            eventDict[seId] = parseEventData(seId, eventItems, data[dataPtr:dataPtr+devLen])
            logDevice("event:         ", seType, seId, devLen, eventDict[seId], eventItems)
        else:   # unknown device type
            raise Exception("Unknown device 0x%04x" % seType) 
        dataPtr += devLen
    return {"inverters": invDict, "optimizers": optDict, "events": eventDict}

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

def parseEventData(seId, eventItems, devData):
    # unpack data and map to items
    seEventData = [struct.unpack(eventInFmt, devData[:invInFmtLen])[i] for i in eventIdx]
    seEventData[2] = time.asctime(time.localtime(seEventData[2]))
    if seEventData[1] == 0:
        seEventData[3] = time.asctime(time.localtime(seEventData[3]))
    else:
        seEventData[4] = time.asctime(time.localtime(seEventData[4]))    
    return devDataDict(seId, eventItems, seEventData)

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
invItems = ["Date", "Time", "ID", "Uptime", "Interval", "Temp", "Eday", "Eac", "Vac", "Iac", "Freq", "Vdc", "Etot", "Pmax", "Pac"]

def parseInvData(seId, invItems, devData):
    # unpack data and map to items
    seInvData = [struct.unpack(invInFmt, devData[:invInFmtLen])[i] for i in invIdx]
    return devDataDict(seId, invItems, seInvData)

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
optItems = ["Date", "Time", "ID", "Inverter", "Uptime", "Vmod", "Vopt", "Imod", "Eday", "Temp"]

def parseOptData(seId, optItems, devData):
    # unpack data and map to items
    seOptData = [struct.unpack(optInFmt, devData[:optInFmtLen])[i] for i in optIdx]
    seOptData[1] = parseId(seOptData[1])
    return devDataDict(seId, optItems, seOptData)

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
def parseNewOptData(seId, optItems, devData):
    data = bytearray()
    data.extend(devData)
    (timeStamp, uptime) = struct.unpack("<LH", devData[0:6])
    vpan = 0.125 * (data[6] | (data[7] <<8 & 0x300))
    vopt = 0.125 * (data[7] >>2 | (data[8] <<6 & 0x3c0))
    imod = 0.00625 * (data[9] <<4 | (data[8] >>4 & 0xf))
    eday = 0.25 * (data[11] <<8 | data[10])
    temp = 1.6 * struct.unpack("<b", devData[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return devDataDict(seId, optItems, [timeStamp, 0, 0, uptime, vpan, vopt, imod, eday, temp])

# create a dictionary of device data items
def devDataDict(seId, itemNames, itemValues):
    devDict = {}
    devDict["Date"] = formatDateStamp(itemValues[0])
    devDict["Time"] = formatTimeStamp(itemValues[0])
    devDict["ID"] = seId
    for i in range(3, len(itemNames)):
        devDict[itemNames[i]] = itemValues[i-2]
    return devDict
    
# write device data to json file
def writeJson(jsonFile, devDict, seq):
    seq += 1
    msg = json.dumps(devDict)
    logMsg("<--", seq, msg, jsonFile.name)
    debug("debugData", msg)
    jsonFile.write(msg+"\n")
    jsonFile.flush()
    return seq
    
# write output file headers
def writeHeaders(outFile, items):
    outFile.write(delim.join(item for item in items)+"\n")

# write data to output files
def writeData(msgDict, invFile, optFile, jsonFile):
    global invSeq, optSeq, jsonSeq
    if invFile:
        if headers and invSeq == 0:
            writeHeaders(invFile, invItems)
        for seId in msgDict["inverters"].keys():
            invSeq = writeDevData(invFile, invOutFmt, msgDict["inverters"][seId], invItems, invSeq)
    if optFile:
        if headers and optSeq == 0:
            writeHeaders(optFile, optItems)
        for seId in msgDict["optimizers"].keys():
            optSeq = writeDevData(optFile, optOutFmt, msgDict["optimizers"][seId], optItems, optSeq)
    if jsonFile:
        jsonSeq = writeJson(jsonFile, msgDict, jsonSeq)
        
# write device data to output file
# device data output file format strings
invOutFmt = ["%s", "%s", "%s", "%d", "%d", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f"]
optOutFmt = ["%s", "%s", "%s", "%s", "%d", "%f", "%f", "%f", "%f", "%f"]
def writeDevData(outFile, outFmt, devDict, devItems, devSeq):
    if outFile:
        outMsg = delim.join([(outFmt[i] % devDict[devItems[i]]) for i in range(len(devItems))])
        try:
            devSeq += 1
            logMsg("<--", devSeq, outMsg, outFile.name)
            debug("debugData", outMsg)
            outFile.write(outMsg+"\n")
            outFile.flush()
        except:
            terminate(1, "Error writing output file "+outFile.name)
    return devSeq

# remove the extra bit that is sometimes set in a device ID and upcase the letters
def parseId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# format a date        
def formatDateStamp(timeStamp):
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

# format a time       
def formatTimeStamp(timeStamp):
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))

# formatted print of device data
def logDevice(devName, seType, seId, devLen, devData, devItems):
    debug("debugData", devName)
    debug("debugData","    type :", "%04x" % seType)
    debug("debugData","    id :", "%s" % seId)
    debug("debugData","    len :", "%04x" % devLen)
    for item in devItems:
        debug("debugData","   ", item, ":", devData[item])


