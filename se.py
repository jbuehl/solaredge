#!/usr/bin/python

# Read a PCAP file that is a capture of the traffic between a SolarEdge inverter and the SE server.
# Filter out and parse the log data for inverters and optimizers.

import cherrypy
import os
import socket
import struct
import sys
import time
import json

from BTUtils import *

# configuration
defaultConfig = {"debug": False,
                 "debugData": False,
                 "httpPort": 80,
                 "latLong": (34.1486, -118.3965),
                 "tempScale": "F",
                 "seHostName": "prod.solaredge.com",
                 "sleepInterval": 10,
                 "histFileName": "history.json"}

class DeviceList(object):
    def __init__(self, theName, theDevices):
        self.name = theName
        self.devices = theDevices

    def add(self, theDevice):
        self.devices.append(theDevice)
        
    def find(self, theName):
        for device in self.devices:
            if device.name == theName:
                return device
        return None

    def findSerial(self, theSerial):
        for device in self.devices:
            if device.serial == theSerial:
                return device
        return None

class Module(object):
    def __init__(self, theName, theType, Pmpp):
        self.name = theName
        self.type = theType
        self.Pmpp = Pmpp

class Array(object):
    def __init__(self, theName, theTilt, theAzimuth):
        self.name = theName
        self.tilt = theTilt
        self.azimuth = theAzimuth

class String(object):
    def __init__(self, theName, theOptimizers):
        self.name = theName
        self.optimizers = theOptimizers

class Inverter(object):
    def __init__(self, theName, theSerial, theStrings, theData=[0]*26):
        self.name = theName
        self.serial = theSerial
        self.strings = theStrings
        self.update(theData)

    def update(self, seInvData):
        self.timeStamp = time.strftime("%H:%M:%S", time.localtime(seInvData[0]))
        self.Uptime = seInvData[1] # uptime (secs) ?
        self.Interval = seInvData[2] # time in last interval (secs) ?
        self.Temp = seInvData[3]*9/5+32 # temperature (F)
        self.Eday = seInvData[4] # energy produced today (Wh)
        self.Eac = seInvData[5] # energy produced in last interval (Wh)
        self.Vac = seInvData[6] # AC volts
        self.Iac = seInvData[7] # AC current
        self.freq = seInvData[8] # frequency (Hz)
        self.data9 = seInvData[9] # 0xff7fffff
        self.data10 = seInvData[10] # 0xff7fffff
        self.Vdc = seInvData[11] # DC volts
        self.data12 = seInvData[12] # 0xff7fffff
        self.Etot = seInvData[13] # total energy produced (Wh)
        self.data14 = seInvData[14] # ?
        self.data15 = seInvData[15] # 0xff7fffff
        self.data16 = seInvData[16] # 0.0
        self.data17 = seInvData[17] # 0.0
        self.Pmax = seInvData[18] # max power (W) = 5000
        self.data19 = seInvData[19] # 0.0
        self.data20 = seInvData[20] # ?
        self.data21 = seInvData[21] # 0xff7fffff
        self.data22 = seInvData[22] # 0xff7fffff
        self.Pac = seInvData[23] # AC power (W)
        self.data24 = seInvData[24] # ?
        self.data25 = seInvData[25] # 0xff7fffff

    def addOpt(self, optId):
        if optId not in self.optimizers:
            self.optimizers.append(optId)
            
class Optimizer(object):
    def __init__(self, theName, theSerial, theArray, theModule, theData=[0]*9):
        self.name = theName
        self.serial = theSerial
        self.array = theArray
        self.module = theModule
        self.update(theData)

    def update(self, seOptData):
        self.timeStamp = time.strftime("%H:%M:%S", time.localtime(seOptData[0]))
        self.inverter = "%x" % (seOptData[1] & 0xff7fffff)
        self.Uptime = seOptData[3] # uptime (secs) ?
        self.Vmod = seOptData[4] # module voltage
        self.Vopt = seOptData[5] # optimizer voltage
        self.Imod = seOptData[6] # module current
        self.Eday = seOptData[7] # energy produced today (Wh)
        self.Temp = seOptData[8]*9/5+32 # temperature (F)

# device mapping

modules = DeviceList("modules", [
    Module("mod1", "Renesola JC300M-24/Ab", 300)
])

arrays = DeviceList("arrays", [
    Array("South", 18.5, 180),
    Array("West", 18.5, 270),
    Array("Extra", 27, 180)
])

optimizers = DeviceList("optimizers", [
    Optimizer("opt01", "100F7220", "South", "mod1"),	#B1
    Optimizer("opt02", "100F746B", "South", "mod1"),	#FE
    Optimizer("opt03", "100F74DB", "South", "mod1"),	#6E
    Optimizer("opt04", "100F72C1", "South", "mod1"),	#52
    Optimizer("opt05", "100F7333", "South", "mod1"),	#C5
    Optimizer("opt06", "100F7335", "South", "mod1"),	#C7
    Optimizer("opt07", "100F7401", "South", "mod1"),	#94
    Optimizer("opt08", "100F74A0", "West", "mod1"),	#33
    Optimizer("opt09", "100F714E", "West", "mod1"),	#DE
    Optimizer("opt10", "100E32F9", "West", "mod1"),	#49
    Optimizer("opt11", "100F7195", "West", "mod1"),	#25
    Optimizer("opt12", "100F6FC5", "West", "mod1"),	#53
    Optimizer("opt13", "100F721E", "West", "mod1"),	#AF
    Optimizer("opt14", "100E3326", "West", "mod1"),	#77
    Optimizer("opt15", "100E3520", "West", "mod1"),	#73
    Optimizer("opt16", "100F74B7", "West", "mod1"),	#4A
    Optimizer("opt17", "100F755D", "West", "mod1"),	#F1
    Optimizer("opt18", "100E34EC", "West", "mod1"),	#3E
    Optimizer("opt19", "100F747C", "West", "mod1"),	#0F
    Optimizer("opt20", "100F7408", "West", "mod1"),	#9B
    Optimizer("opt21", "100E3313", "West", "mod1"),	#64
    Optimizer("opt22", "100F707C", "West", "mod1"),	#0B
    Optimizer("opt23", "100F7118", "West", "mod1"),	#A8
    Optimizer("opt24", "100F74D9", "West", "mod1"),	#6C
    Optimizer("opt25", "100F719B", "West", "mod1"),	#2B
    Optimizer("opt26", "100F71F9", "West", "mod1"),	#89
    Optimizer("opt27", "100F7237", "West", "mod1"),	#C8
    Optimizer("opt28", "100F74C6", "West", "mod1"),	#59
    Optimizer("opt29", "100F743D", "West", "mod1"),	#D0
    Optimizer("opt30", "100E3325", "West", "mod1"),	#76
    Optimizer("opt31", "100F71E5", "West", "mod1"),	#75
    Optimizer("opt32", "100F7255", "West", "mod1"),	#E6
    Optimizer("opt33", "1016AB88", "Extra", "mod1"),	#59
    Optimizer("opt34", "1016B2BB", "Extra", "mod1"),	#93
])

strings = DeviceList("strings", [
    String("str1", ["opt01", "opt02", "opt03", "opt04", "opt05", "opt06", "opt07"]),
    String("str2", ["opt08", "opt09", "opt10", "opt11", "opt12", "opt13", "opt14", "opt15"]),
    String("str3", ["opt16", "opt17", "opt18", "opt19", "opt20", "opt21", "opt22", "opt23", "opt24", 
                    "opt25", "opt26", "opt27", "opt28", "opt29", "opt30", "opt31", "opt32"]),
    String("str4", ["opt33", "opt34"]),
])

inverters = DeviceList("inverters", [
    Inverter("inv1", "7F104920", ["str3"]),	#F8
    Inverter("inv2", "7F104A16", ["str1", "str2", "str4"]),	#EF
])

# file constants
pcapFileHdrLen = 24
pcapRecHdrLen = 16
etherHdrLen = 14
ipHdrLen = 20
tcpHdrLen = 20
seHdrLen = 20
seDevHdrLen = 8

# PCAP file header
def readPcapHdr(pcapFile):
    return struct.unpack("<LHHLLLL", pcapFile.read(pcapFileHdrLen))

# PCAP record header
def readPcapRec(pcapFile):
    pcapBuf = pcapFile.read(pcapRecHdrLen)
    if pcapBuf:
        return struct.unpack("<LLLL", pcapBuf)
    else:
        return None

# Ethernet header    
def readEthHdr(pcapFile):
    return pcapFile.read(etherHdrLen)

# IP header
def readIpHdr(pcapFile):
    return struct.unpack("!LLLLL", pcapFile.read(ipHdrLen))
    
# TCP header
def readTcpHdr(pcapFile):
    return struct.unpack("<LLLLL", pcapFile.read(tcpHdrLen))

# SolarEdge data
def readSe(pcapFile, app):
    (seDataLen, se1, se2) = readSeHdr(pcapFile)
    # ignore records that aren't type 0xfe or are shorter than a device record
    if (seDataLen < seDevHdrLen) or (se2 != 0xfe):
        seData = pcapFile.read(seDataLen)
        seDataLen = 0
    else:
        while seDataLen > 0:
            seDevice = struct.unpack("<HLH", pcapFile.read(seDevHdrLen))
            seType = seDevice[0]
            seId = ("%x" % (seDevice[1] & 0xff7fffff)).upper()
            seDeviceLen = seDevice[2]
            if app.debugData: app.log("solaredge", "seType", "%4x" % seType, "seId", seId, "seDeviceLen", seDeviceLen)
            if seType == 0x0000:    # optimizer
#                if app.debugData: app.log( "seId", seId)
                seOptData = readOpt(pcapFile, seDeviceLen)
                try:
                    if app.debugObject: app.log("optimizer", optimizers.findSerial(seId).name, "updating", seId)
                    optimizers.findSerial(seId).update(seOptData)
                except:
                    if app.debugObject: app.log("optimizer", optimizers.findSerial(seId).name, "creating", seId)
                    optimizers.add(Optimizer(seId, seId, [], seOptData))
            elif seType == 0x0010:  # inverter
#                if app.debugData: app.log( "seId", seId)
                seInvData = readInv(pcapFile, seDeviceLen)
                try:
                    if app.debugObject: app.log("inverter", inverters.findSerial(seId).name, "updating", seId)
                    inverters.findSerial(seId).update(seInvData)
                    updateHist(app)
                except:
                    if app.debugObject: app.log("inverter", inverters.findSerial(seId).name, "creating", seId)
                    inverters.add(Inverter(seId, seId, [], seInvData))
            elif seType == 0x0200:
                seData = pcapFile.read(seDeviceLen)
            else:
                seData = pcapFile.read(seDataLen - seDevHdrLen)
            seDataLen -= seDeviceLen + seDevHdrLen
    seCksum = struct.unpack("!H", pcapFile.read(2))
    if seDataLen:
        if app.debugData: app.log("solaredge", "len", seDataLen, "cksum", "%x" % seCksum)

# SolarEdge header
def readSeHdr(pcapFile):
    seHdr = struct.unpack("<LHBBHHHHHH", pcapFile.read(seHdrLen))
    if app.debugData: app.log("solaredge", "seHdr", "%x "*10 % seHdr)
    return (seHdr[1], seHdr[2], seHdr[3])

# Inverter data
def readInv(pcapFile, seDeviceLen):
    return struct.unpack("<LLLffffffLLfLffLfffffLLffL", pcapFile.read(seDeviceLen))

# Optimizer data    
def readOpt(pcapFile, seDeviceLen):
    return struct.unpack("<LLLLfffff", pcapFile.read(seDeviceLen))

class WebRoot(object):
    def __init__(self, theApp):
        self.app = theApp

    @cherrypy.expose
    def history(self):
        return json.dumps(readHist(self.app))

    @cherrypy.expose
    def optimizers(self, id=None):
        return self.getObject(optimizers, id)

    @cherrypy.expose
    def inverters(self, id=None):
        return self.getObject(inverters, id)

    @cherrypy.expose
    def strings(self, id=None):
        return self.getObject(strings, id)

    @cherrypy.expose
    def arrays(self, id=None):
        return self.getObject(arrays, id)

    @cherrypy.expose
    def modules(self, id=None):
        return self.getObject(modules, id)

    def getObject(self, objList, id):
        if id:
            return json.dumps(objList.find(id).__dict__)
        else:
            keyList = []
            for obj in objList.devices:
                keyList.append(obj.name)
            return json.dumps(keyList)

def updateHist(app):
    today = time.strftime("%Y%m%d")
    Eday = 0.0
    for inverter in inverters.devices:
        Eday += inverter.Eday
    if app.debugObject: app.log(today, "updated %f"%Eday)
    history = readHist(app)
    history[today] = Eday
    writeHist(app, history)

def readHist(app):
    histFile = open(app.histFileName)
    history = json.load(histFile)
    histFile.close()
    return history
    
def writeHist(app, history):
    histFile = open(app.histFileName, "w")
    histFile.write(json.dumps(history))
    histFile.close()
    
# return the latest pcap file in the specified directory
def openFile(pcapDirName, pcapFileName, pcapFile, pcapSeq):
    lastFileName = pcapDirName+"/"+os.listdir(pcapDirName)[-1]
    if pcapFileName != lastFileName:    # is there a new file?
        if pcapFile:                    # is a file currently open?
            if app.debug: app.log("app", "closing", pcapFileName)
            pcapFile.close()
        pcapFileName = lastFileName
        if app.debug: app.log("app", "opening", pcapFileName)
        pcapFile = open(pcapFileName)
        pcapSeq = 0
        pcapHdr = readPcapHdr(pcapFile)
    return (pcapFileName, pcapFile, pcapSeq)

if __name__ == "__main__":
    app = BTApp("se.conf", "se.log", defaultConfig)

    # web interface
    globalConfig = {
                    'server.socket_port': app.httpPort,
                    'server.socket_host': "0.0.0.0",
                    }
    cherrypy.config.update(globalConfig)
    root = WebRoot(app)
    cherrypy.tree.mount(root, "/", {})
    cherrypy.engine.start()

    # IP address of the SolarEdge server    
    seIpAddr = struct.unpack("!I", socket.inet_aton(socket.gethostbyname_ex(app.seHostName)[2][0]))[0]    # 0xd9449842        
    if app.debug: app.log("app", "host", seIpAddr)

    # open the latest pcap file    
    pcapFileName = ""
    pcapFile = 0
    pcapSeq = 0
    pcapDirName = sys.argv[1].strip("/")
    (pcapFileName, pcapFile, pcapSeq) = openFile(pcapDirName, pcapFileName, pcapFile, pcapSeq)
    
    # read forever
    while True:
        pcapRec = readPcapRec(pcapFile)
        if pcapRec:
            pcapSeq += 1
            pcapRecLen = pcapRec[2]
            etherHdr = readEthHdr(pcapFile)
            ipHdr = readIpHdr(pcapFile)
            ipSrc = ipHdr[3]
            ipDst = ipHdr[4]
            tcpHdr = readTcpHdr(pcapFile)
            dataLen = pcapRecLen - etherHdrLen - ipHdrLen - tcpHdrLen
            if app.debugData: app.log("pcap", "pcapSeq", pcapSeq, "pcapRecLen", pcapRecLen, "dataLen", dataLen)
            if ipDst == seIpAddr:   # filter traffic to SE
                if dataLen > seHdrLen:
                    dataLen = 0
                    readSe(pcapFile, app)
            if dataLen:
                pcapFile.read(dataLen)
        else:   # end of file - wait a bit and see if there is more data
            time.sleep(app.sleepInterval)
            (pcapFileName, pcapFile, pcapSeq) = openFile(pcapDirName, pcapFileName, pcapFile, pcapSeq)

