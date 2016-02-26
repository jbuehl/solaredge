# SolarEdge data protocol

import struct
import json

from seConf import *

devHdrLen = 8
statusLen = 14

# device data dictionaries
invDict = {}
optDict = {}

# parse status data
def convertStatus(msg):
    status = struct.unpack("<HHHHHHH", msg)
    debug("debugData", "status", "%d "*len(status) % status)

# parse device data
def convertDevice(devData, invFile, optFile, jsonFileName):
    global invDict, optDict
    dataPtr = 0
    while dataPtr < len(devData):
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", devData[dataPtr:dataPtr+devHdrLen])
        seId = convertId(seId)
        dataPtr += devHdrLen
        # device data
        if seType == 0x0000:    # optimizer data
            optDict[seId] = convertOptData(seId, optItems, devData[dataPtr:dataPtr+devLen])
            logDev("optimizer:     ", seType, seId, devLen, optDict[seId], optItems)
            writeData(optFile, optOutFmt, optDict[seId], optItems)
        elif seType == 0x0080:  # new format optimizer data
            optDict[seId] = convertNewOptData(seId, optItems, devData[dataPtr:dataPtr+devLen])
            logDev("optimizer:     ", seType, seId, devLen, optDict[seId], optItems)
            writeData(optFile, optOutFmt, optDict[seId], optItems)
        elif seType == 0x0010:  # inverter data
            invDict[seId] = convertInvData(seId, invItems, devData[dataPtr:dataPtr+devLen])
            logDev("inverter:     ", seType, seId, devLen, invDict[seId], invItems)
            writeData(invFile, invOutFmt, invDict[seId], invItems)
        else:   # unknown device type
            raise Exception("Unknown device 0x%04x" % seType) 
        dataPtr += devLen

# inverter data interpretation
#
#   timeStamp = seData[0]
#   Uptime = seData[1] # uptime (secs) ?
#   Interval = seData[2] # time in last interval (secs) ?
#   Temp = seData[3] # temperature (C)
#   Eday = seData[4] # energy produced today (Wh)
#   Eac = seData[5] # energy produced in last interval (Wh)
#   Vac = seData[6] # AC volts
#   Iac = seData[7] # AC current
#   freq = seData[8] # frequency (Hz)
#   data9 = seData[9] # 0xff7fffff
#   data10 = seData[10] # 0xff7fffff
#   Vdc = seData[11] # DC volts
#   data12 = seData[12] # 0xff7fffff
#   Etot = seData[13] # total energy produced (Wh)
#   data14 = seData[14] # ?
#   data15 = seData[15] # 0xff7fffff
#   data16 = seData[16] # 0.0
#   data17 = seData[17] # 0.0
#   Pmax = seData[18] # max power (W) = 5000
#   data19 = seData[19] # 0.0
#   data20 = seData[20] # ?
#   data21 = seData[21] # 0xff7fffff
#   data22 = seData[22] # 0xff7fffff
#   Pac = seData[23] # AC power (W)
#   data24 = seData[24] # ?
#   data25 = seData[25] # 0xff7fffff
    
# format string used to unpack input data
invInFmt = "<LLLffffffLLfLffLfffffLLffL"
# mapping of input data to device data items
invIdx = [0,1,2,3,4,5,6,7,8,11,13,18,23]
# device data item names
invItems = ["Date", "Time", "ID", "Uptime", "Interval", "Temp", "Eday", "Eac", "Vac", "Iac", "Freq", "Vdc", "Etot", "Pmax", "Pac"]

def convertInvData(seId, invItems, devData):
    # unpack data and map to items
    seInvData = [struct.unpack(invInFmt, devData)[i] for i in invIdx]
    return devDataDict(seId, invItems, seInvData)

# optimizer data interpretation
#
#   timeStamp = seData[0]
#   inverter = seData[1] & 0xff7fffff
#   Uptime = seData[3] # uptime (secs) ?
#   Vmod = seData[4] # module voltage
#   Vopt = seData[5] # optimizer voltage
#   Imod = seData[6] # module current
#   Eday = seData[7] # energy produced today (Wh)
#   Temp = seData[8] # temperature (C)

# format string used to unpack input data
optInFmt = "<LLLLfffff"
# mapping of input data to device data items
optIdx = [0,1,3,4,5,6,7,8]
# device data item names
optItems = ["Date", "Time", "ID", "Inverter", "Uptime", "Vmod", "Vopt", "Imod", "Eday", "Temp"]

def convertOptData(seId, optItems, devData):
    # unpack data and map to items
    seOptData = [struct.unpack(optInFmt, devData)[i] for i in optIdx]
    seOptData[1] = convertId(seOptData[1])
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
def convertNewOptData(seId, optItems, devData):
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
    devDict["Date"] = printDate(itemValues[0])
    devDict["Time"] = printTime(itemValues[0])
    devDict["ID"] = seId
    for i in range(3, len(itemNames)):
        devDict[itemNames[i]] = itemValues[i-2]
    return devDict
    
# write device data to json file
def writeJson():
    if jsonFileName != "":
        debug("debugMsgs", "writing", jsonFileName)
        json.dump({"inverters": invDict, "optimizers": optDict}, open(jsonFileName, "w"))
    
# write output file headers
def writeHeaders(outFile, items, delim):
    outFile.write(delim.join(item for item in items)+"\n")

# write device data to output file
# device data output file format strings
invOutFmt = ["%s", "%s", "%s", "%d", "%d", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f", "%f"]
optOutFmt = ["%s", "%s", "%s", "%s", "%d", "%f", "%f", "%f", "%f", "%f"]
def writeData(outFile, outFmt, devDict, devItems):
    if outFile:
        outMsg = delim.join([(outFmt[i] % devDict[devItems[i]]) for i in range(len(devItems))])
        try:
            logMsg("<--", 0, outMsg, outFile.name)
            debug("debugData", outMsg)
            outFile.write(outMsg+"\n")
            outFile.flush()
        except:
            terminate(1, "Error writing output file "+outFile.name)

# remove the extra bit that is sometimes set in a device ID and upcase the letters
def convertId(seId):
    return ("%x" % (seId & 0xff7fffff)).upper()

# format a date        
def printDate(timeStamp):
    return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

# format a time       
def printTime(timeStamp):
    return time.strftime("%H:%M:%S", time.localtime(timeStamp))

# formatted print of device data
def logDev(devName, seType, seId, devLen, devData, devItems):
    debug("debugData", devName)
    debug("debugData","    type :", "%04x" % seType)
    debug("debugData","    id :", "%s" % seId)
    debug("debugData","    len :", "%04x" % devLen)
    for item in devItems:
        debug("debugData","   ", item, ":", devData[item])


