# SolarEdge data interpretation

import struct
import json
from seConf import *
from seCommands import *
from seDataParams import *
from seDataDevices import ParseDevice, merge_update, unwrap_metricsDict
                    
# message debugging sequence numbers
outSeq = 0

# parse the message data
def parseData(function, data):
    if function in [PROT_RESP_ACK, PROT_RESP_NACK, PROT_CMD_MISC_GET_VER,
                      PROT_CMD_MISC_GET_TYPE, PROT_CMD_SERVER_GET_GMT,
                      PROT_CMD_SERVER_GET_NAME, PROT_CMD_POLESTAR_GET_STATUS,
                      PROT_CMD_POLESTAR_MASTER_GRANT, PROT_RESP_POLESTAR_MASTER_GRANT_ACK]:
        # functions with no arguments
        return ''.join(x.encode('hex') for x in data)
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
    elif function == PROT_RESP_POLESTAR_GET_ENERGY_STATISTICS_STATUS:
        return parseEnergyStats(data)
    elif function == 0x0503:
        return {}
    else:
        # unknown function type
        log("Unknown function 0x%04x" % function)
    return ''.join(x.encode('hex') for x in data)

def parseEnergyStats(data):
    (Eday, Emon, Eyear, Etot, Time1) = struct.unpack("<ffffL", data[0:20])
    return {"Eday": Eday, "Emon": Emon, "Eyear": Eyear, "Etot": Etot, 
            "Time1": formatDateTime(Time1)}
    
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
#    if len(data) > 0:
#        status = struct.unpack("<HHHHHHH", data)
#        debug("debugData", "status", "%d "*len(status) % status)
#    return {"status": status}
    logData(data)
    return {"status": 0}

# parse device data
def parseDeviceData(data):
    devHdrLen = 8
    invDict = {}
    optDict = {}
    eventDict = {}
    # Add a master dictionary, to store anything parsed by ParseDevice, indexed by the `_devType`
    devsDict = {}

    dataPtr = 0
    while dataPtr < len(data):
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", data[dataPtr:dataPtr+devHdrLen])
        seId = parseId(seId)
        dataPtr += devHdrLen
        # device data
        if seType == 0x0000:    # optimizer data
            optDict[seId] = parseOptData(seId, optItems, data[dataPtr:dataPtr+devLen])
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId])
        elif seType == 0x0080:  # new format optimizer data
            optDict[seId] = parseNewOptData(seId, optItems, data[dataPtr:dataPtr+devLen])
            logDevice("optimizer:     ", seType, seId, devLen, optDict[seId])
        elif seType == 0x0010:  # inverter data
            invDict[seId] = parseInvData(seId, invItems, data[dataPtr:dataPtr+devLen])
            logDevice("inverter:     ", seType, seId, devLen, invDict[seId])
        elif seType == 0x0011:  # 3 phase inverter data
            invDict[seId] = parseInv3PhData(seId, inv3PhItems, data[dataPtr:dataPtr+devLen])
            logDevice("inverter:     ", seType, seId, devLen, invDict[seId])
        elif seType == 0x0300:  # wake or sleep event
            eventDict[seId] = parseEventData(seId, eventItems, data[dataPtr:dataPtr+devLen])
            logDevice("event:         ", seType, seId, devLen, eventDict[seId])
        else:   # unknown device type, or one that ParseDevice can handle
            # log("Unknown device 0x%04x" % seType)
            # logData(data[dataPtr-devHdrLen:dataPtr+devLen])

            # In production would usually set explorer to False, to prevent excessively long (and mostly useless) parse
            # results for unknown device types.
            parsedDevice = ParseDevice(data[dataPtr - devHdrLen:dataPtr + devLen], explorer=False)
            # Add the new device attributes (wrapped in  dictionary of appropriate identifiers) to the dictionary of devices
            merge_update(devsDict, parsedDevice.wrap_in_ids())
            logDevice("{}: ".format(parsedDevice._devType), seType, seId, devLen, parsedDevice.wrap_in_ids())

        dataPtr += devLen
    # A bit of a lazy way out, but embed the pre-existing dictionaries into devsDict
    devsDict["inverters"] = invDict
    devsDict["optimizers"] = optDict
    devsDict["events"] = eventDict

    return devsDict

def parseEventData(seId, eventItems, devData):
    # unpack data and map to items
    seEventData = [struct.unpack(eventInFmt, devData[:invInFmtLen])[i] for i in eventIdx]
    seEventData[2] = formatDateTime(seEventData[2])
    if seEventData[1] == 0:
        seEventData[3] = formatDateTime(seEventData[3])
    else:
        seEventData[4] = formatDateTime(seEventData[4])    
    return devDataDict(seId, eventItems, seEventData)

def parseInvData(seId, invItems, devData):
    # unpack data and map to items
    seInvData = [struct.unpack(invInFmt, devData[:invInFmtLen])[i] for i in invIdx]
    return devDataDict(seId, invItems, seInvData)

def parseInv3PhData(seId, invItems, devData):
    # unpack data and map to items
    seInvData = [struct.unpack(inv3PhInFmt, devData[:inv3PhInFmtLen])[i] for i in inv3PhIdx]
    return devDataDict(seId, invItems, seInvData)

def parseOptData(seId, optItems, devData):
    # unpack data and map to items
    seOptData = [struct.unpack(optInFmt, devData[:optInFmtLen])[i] for i in optIdx]
    seOptData[1] = parseId(seOptData[1])
    return devDataDict(seId, optItems, seOptData)

def parseNewOptData(seId, optItems, devData):
    data = bytearray()
    data.extend(devData)
    (timeStamp, uptime) = struct.unpack("<LH", devData[0:6])
    vpan = 0.125 * (data[6] | (data[7] <<8 & 0x300))
    vopt = 0.125 * (data[7] >>2 | (data[8] <<6 & 0x3c0))
    imod = 0.00625 * (data[9] <<4 | (data[8] >>4 & 0xf))
    eday = 0.25 * (data[11] <<8 | data[10])
    temp = 2.0 * struct.unpack("<b", devData[12:13])[0]
    # Don't have an inverter ID in the data, substitute 0
    return devDataDict(seId, optItems, [timeStamp, 0, uptime, vpan, vopt, imod, eday, temp])

# create a dictionary of device data items
def devDataDict(seId, itemNames, itemValues):
    devDict = {}
    devDict["Date"] = formatDateStamp(itemValues[0])
    devDict["Time"] = formatTimeStamp(itemValues[0])
    devDict["ID"] = seId
    for i in range(3, len(itemNames)):
        devDict[itemNames[i]] = itemValues[i-2]
    return devDict
    
# write device data to output files
def writeData(msgDict, outFile):
    global outSeq
    if outFile:
        outSeq += 1
        msg = json.dumps(msgDict)
        logMsg("<--", outSeq, msg, outFile.name)
        debug("debugData", msg)
        outFile.write(msg+"\n")
        outFile.flush()
        
# remove the extra bit that is sometimes set in a device ID and upcase the letters
def parseId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# format a date        
def formatDateStamp(timeStamp):
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

# format a time       
def formatTimeStamp(timeStamp):
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))

# format a timestamp using asctime
# return the hex value if timestamp is invalid
def formatDateTime(timeStamp):
    try:
        return time.asctime(time.localtime(timeStamp))
    except ValueError:
        return ''.join(x.encode('hex') for x in timeStamp)
        
# formatted print of device data
def logDevice(devType, seType, seId, devLen, devData):
    debug("debugData", devType, seId, "type: %04x" % seType, "len: %04x" % devLen)
    for item in devData.keys():
        debug("debugData","   ", item, ":", devData[item])

