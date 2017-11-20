#!/usr/bin/env python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

import time
import threading
from seConf import *
from seFiles import *
from seMsg import *
from seData import *
from seCommands import *

# global variables
threadLock = threading.Lock()  # lock to synchronize reads and writes
masterEvent = threading.Event()  # event to signal RS485 master release
running = True


# process the input data
def readData(dataFile, recFile, outFile):
    if updateFileName != "":  # create an array of zeros for the firmware update file
        updateBuf = list('\x00' * updateSize)
    if passiveMode:
        msg = readMsg(
            dataFile,
            recFile)  # skip data until the start of the first complete message
    while running:
        msg = readMsg(dataFile, recFile)
        if msg == "":  # end of file
            # eof from network means connection was broken, wait for a reconnect and continue
            if networkDevice:
                closeData(dataFile)
                dataFile = openDataSocket()
            else:  # all finished
                if updateFileName != "":  # write the firmware update file
                    writeUpdate()
                return
        if msg == "\x00" * len(msg):  # ignore messages containing all zeros
            if debugData: logData(msg)
        else:
            with threadLock:
                try:
                    processMsg(msg, dataFile, recFile, outFile)
                except Exception as ex:
                    debug("debugEnable", "Exception:", ex.args[0])
                    if haltOnException:
                        logData(msg)
                        raise


# process a received message
def processMsg(msg, dataFile, recFile, outFile):
    # parse the message
    (msgSeq, fromAddr, toAddr, function, data) = parseMsg(msg)
    if function == 0:
        # message could not be processed
        debug("debugData", "Ignoring this message")
        logData(data)
    else:
        msgData = parseData(function, data)
        if (function == PROT_CMD_SERVER_POST_DATA) and (
                data != ""):  # performance data
            # write performance data to output file
            writeData(msgData, outFile)
        elif (updateFileName != ""
              ) and function == PROT_CMD_UPGRADE_WRITE:  # firmware update data
            updateBuf[msgData["offset"]:
                      msgData["offset"] + msgData["length"]] = msgData["data"]
        if (networkDevice or masterMode):  # send reply
            replyFunction = ""
            if function == PROT_CMD_SERVER_POST_DATA:  # performance data
                # send ack
                replyFunction = PROT_RESP_ACK
                replyData = ""
            elif function == 0x0503:  # encryption key
                # send ack
                replyFunction = PROT_RESP_ACK
                replyData = ""
            elif function == PROT_CMD_SERVER_GET_GMT:  # time request
                # set time
                replyFunction = PROT_RESP_SERVER_GMT
                replyData = formatTime(
                    int(time.time()),
                    (time.localtime().tm_hour - time.gmtime().tm_hour) * 60 *
                    60)
            elif function == PROT_RESP_POLESTAR_MASTER_GRANT_ACK:  # RS485 master release
                masterEvent.set()
            if replyFunction != "":
                msg = formatMsg(msgSeq, toAddr, fromAddr, replyFunction,
                                replyData)
                sendMsg(dataFile, msg, recFile)


# write firmware image to file
def writeUpdate():
    updateBuf = "".join(updateBuf)
    debug("debugFiles", "writing", updateFileName)
    with open(updateFileName, "w") as updateFile:
        updateFile.write(updateBuf)


# RS485 master commands thread
def masterCommands(dataFile, recFile):
    while running:
        for slaveAddr in slaveAddrs:
            with threadLock:
                # grant control of the bus to the slave
                sendMsg(dataFile,
                        formatMsg(nextSeq(), masterAddr, int(slaveAddr, 16),
                                  PROT_CMD_POLESTAR_MASTER_GRANT), recFile)

            def masterTimerExpire():
                debug("debugMsgs", "RS485 master ack timeout")
                masterEvent.set()

            # start a timeout to release the bus if the slave doesn't respond
            masterTimer = threading.Timer(masterMsgTimeout, masterTimerExpire)
            masterTimer.start()
            # wait for slave to release the bus
            masterEvent.clear()
            masterEvent.wait()
            # cancel the timeout
            masterTimer.cancel()
        time.sleep(masterMsgInterval)


# perform the specified commands
def doCommands(dataFile, commands, recFile):
    slaveAddr = int(slaveAddrs[0], 16)
    if masterMode:  # send RS485 master command
        # grant control of the bus to the slave
        sendMsg(dataFile,
                formatMsg(nextSeq(), masterAddr, slaveAddr,
                          PROT_CMD_POLESTAR_MASTER_GRANT), recFile)
    for command in commands:
        # format the command parameters
        function = int(command[0], 16)
        format = "<" + "".join(c[0] for c in command[1:])
        params = [int(p[1:], 16) for p in command[1:]]
        seq = nextSeq()
        # send the command
        sendMsg(dataFile,
                formatMsg(seq, masterAddr, slaveAddr, function,
                          struct.pack(format, *tuple(params))), recFile)
        # wait for the response
        msg = readMsg(dataFile, recFile)
        (msgSeq, fromAddr, toAddr, response, data) = parseMsg(msg)
        msgData = parseData(response, data)
        # write response to output file
        writeData({
            "command": function,
            "response": response,
            "sequence": seq,
            "data": msgData
        }, outFile)
        # wait a bit before sending the next one
        time.sleep(commandDelay)


# start RS485 master thread
def startMaster(args):
    # start a thread to poll for data
    masterThread = threading.Thread(
        name=masterThreadName, target=masterCommands, args=args)
    masterThread.start()
    debug("debugFiles", "starting", masterThreadName)


if __name__ == "__main__":
    # initialization
    dataFile = openData(inFileName)
    (recFile, outFile) = openOutFiles(recFileName, outFileName)
    if passiveMode:  # only reading from file or serial device
        # read until eof then terminate
        readData(dataFile, recFile, outFile)
    else:  # reading and writing to network or serial device
        if commandAction:  # commands were specified
            # perform commands then terminate
            doCommands(dataFile, commands, recFile)
        else:  # network or RS485
            # start a thread for reading
            readThread = threading.Thread(
                name=readThreadName,
                target=readData,
                args=(dataFile, recFile, outFile))
            readThread.start()
            debug("debugFiles", "starting", readThreadName)
            if masterMode:  # send RS485 master commands
                startMaster(args=(dataFile, recFile))
            # wait for termination
            running = waitForEnd()
    # cleanup
    closeData(dataFile)
    closeOutFiles(recFile, outFile)
