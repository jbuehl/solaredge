#!/usr/bin/env python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

import time
import threading
import sys
import struct
import se.env
import se.logutils
import se.files
import se.msg
import se.data
import se.commands
import se.network
import logging
from collections import namedtuple
#import logging.handlers

logger = logging.getLogger(__name__)

Files = namedtuple("Files", ("dataFile", "outFile", "recFile", "keyStr"))

# action parameters
COMMAND_DELAY = 2
READ_THREAD_NAME = "read thread"
MASTER_THREAD_NAME = "master thread"
MASTER_MSG_INTERVAL = 5
MASTER_MSG_TIMEOUT = 10
MASTER_ADDR = 0xfffffffe
SEQ_FILE_NAME = "seseq.txt"
UPDATE_SIZE = 0x80000

# global variables
threadLock = threading.Lock()  # lock to synchronize reads and writes
masterEvent = threading.Event()  # event to signal RS485 master release

# program termination
def terminate(code=0, msg=""):
    if code == 0:
        logger.info(msg)
    else:
        logger.error(msg)
    sys.exit(code)

# process the input data
def readData(args, mode, dataFile, recFile, outFile, keyStr):
    updateBuf = list('\x00' * UPDATE_SIZE) if args.updatefile else []
    if mode.passiveMode:
        msg = se.msg.readMsg(dataFile, recFile, mode.passiveMode, mode.serialDevice, mode.following)  # skip data until the start of the first complete message
    while True:
        msg = se.msg.readMsg(dataFile, recFile, mode.passiveMode, mode.serialDevice, mode.following)
        if not msg:  # end of file
            # eof from network means connection was broken, wait for a reconnect and continue
            if mode.networkDevice:
                se.files.closeData(dataFile, True)
                dataFile = se.files.openDataSocket(args.ports)
            else:  # all finished
                if args.updatefile:  # write the firmware update file
                    writeUpdate(updateBuf, args.updatefile)
                return
        if msg == "\x00" * len(msg):  # ignore messages containing all zeros
            logger.data(msg)
        else:
            with threadLock:
                try:
                    processMsg(msg, args, mode, dataFile, recFile, outFile, keyStr, updateBuf)
                except:
                    logger.info("Failed to parse message")
                    for l in se.logutils.format_data(msg):
                        logger.data(l)
                    if args.xerror:
                        raise

# process a received message
def processMsg(msg, args, mode, dataFile, recFile, outFile, keyStr, updateBuf):
    # parse the message
    (msgSeq, fromAddr, toAddr, function, data) = se.msg.parseMsg(msg, keyStr)
    if function == 0:
        # message could not be processed
        logger.data("Ignoring this message")
        for l in se.logutils.format_data(data):
            logger.data(l)
    else:
        msgData = se.data.parseData(function, data)
        if function == se.commands.PROT_CMD_SERVER_POST_DATA and data:  # performance data
            # write performance data to output file
            se.data.writeData(msgData, outFile)
        elif updateBuf and function == se.commands.PROT_CMD_UPGRADE_WRITE:  # firmware update data
            updateBuf[msgData["offset"]:msgData["offset"] + msgData["length"]] = msgData["data"]
        if mode.networkDevice or mode.masterMode:  # send reply
            replyFunction = ""
            if function == se.commands.PROT_CMD_SERVER_POST_DATA:  # performance data
                # send ack
                replyFunction = se.commands.PROT_RESP_ACK
                replyData = ""
            elif function == 0x0503:  # encryption key
                # send ack
                replyFunction = se.commands.PROT_RESP_ACK
                replyData = ""
            elif function == se.commands.PROT_CMD_SERVER_GET_GMT:  # time request
                # set time
                replyFunction = se.commands.PROT_RESP_SERVER_GMT
                replyData = se.data.formatTime(int(time.time()),
                    (time.localtime().tm_hour - time.gmtime().tm_hour) * 60 * 60)
            elif function == se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK:  # RS485 master release
                masterEvent.set()
            if replyFunction != "":
                msg = se.msg.formatMsg(msgSeq, toAddr, fromAddr, replyFunction, replyData)
                se.msg.sendMsg(dataFile, msg, recFile)

# write firmware image to file
def writeUpdate(updateBuf, updateFileName):
    updateBuf = "".join(updateBuf)
    logger.info("writing %s", updateFileName)
    with open(updateFileName, "w") as updateFile:
        updateFile.write(updateBuf)

# RS485 master commands thread
def masterCommands(dataFile, recFile, slaveAddrs):
    while True:
        for slaveAddr in slaveAddrs:
            with threadLock:
                # grant control of the bus to the slave
                se.msg.sendMsg(dataFile,
                            se.msg.formatMsg(nextSeq(), MASTER_ADDR, int(slaveAddr, 16),
                                  se.commands.PROT_CMD_POLESTAR_MASTER_GRANT), recFile)

            def masterTimerExpire():
                logger.debug("RS485 master ack timeout")
                masterEvent.set()

            # start a timeout to release the bus if the slave doesn't respond
            masterTimer = threading.Timer(MASTER_MSG_TIMEOUT, masterTimerExpire)
            masterTimer.start()
            # wait for slave to release the bus
            masterEvent.clear()
            masterEvent.wait()
            # cancel the timeout
            masterTimer.cancel()
        time.sleep(MASTER_MSG_INTERVAL)

# perform the specified commands
def doCommands(args, mode, dataFile, recFile, outFile):
    if mode.masterMode:  # send RS485 master command
        # grant control of the bus to the slave
        se.msg.sendMsg(dataFile,
                se.msg.formatMsg(nextSeq(), MASTER_ADDR, args.slaves[0], se.commands.PROT_CMD_POLESTAR_MASTER_GRANT), 
                recFile)
    for command in args.commands:
        # format the command parameters
        function = int(command[0], 16)
        format = "<" + "".join(c[0] for c in command[1:])
        params = [int(p[1:], 16) for p in command[1:]]
        seq = nextSeq()
        # send the command
        se.msg.sendMsg(dataFile,
                se.msg.formatMsg(seq, MASTER_ADDR, int(args.slaves[0], 16), function,
                          struct.pack(format, *tuple(params))), recFile)
        # wait for the response
        msg = se.msg.readMsg(dataFile, recFile, mode.passiveMode, mode.serialType, mode.following)
        (msgSeq, fromAddr, toAddr, response, data) = se.msg.parseMsg(msg)
        msgData = se.data.parseData(response, data)
        # write response to output file
        se.data.writeData({
            "command": function,
            "response": response,
            "sequence": seq,
            "data": msgData
        }, outFile)
        # wait a bit before sending the next one
        time.sleep(COMMAND_DELAY)

# start RS485 master thread
def startMaster(args):
    # start a thread to poll for data
    masterThread = threading.Thread(
        name=MASTER_THREAD_NAME, target=masterCommands, args=args)
    masterThread.daemon = True
    masterThread.start()
    logger.info("starting %s", MASTER_THREAD_NAME)

# wait until keyboard interrupt
def block():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

# get next sequence number
def nextSeq():
    try:
        with open(SEQ_FILE_NAME) as seqFile:
            seq = int(seqFile.read().rstrip("\n"))
        seq += 1
        if seq > 65535:
            seq = 1
    except IOError:
        seq = 1
    with open(SEQ_FILE_NAME, "w") as seqFile:
        seqFile.write(str(seq) + "\n")
    return seq


if __name__ == "__main__":
    # get the command line arguments and run mode
    (args, mode) = se.env.getArgs()
    
    # open the specified data source
    logger.info("opening %s", args.datasource)
    if args.datasource == "network":
        if args.interface:
            # start network services
            netInterfaceParams = args.interface[2][0]
            se.network.startDhcp(netInterfaceParams["addr"], 
                netInterfaceParams["netmask"], netInterfaceParams["broadcast"])
            se.network.startDns(netInterfaceParams["addr"])
        dataFile =  se.files.openDataSocket(args.ports)
    elif mode.serialDevice:
        dataFile =  se.files.openSerial(args.datasource, args.baudrate)
    else:
        dataFile =  se.files.openInFile(args.datasource)
    # get encryption key
    keyStr = args.keyfile.read().rstrip("\n") if args.keyfile else None

    # open the output files
    recFile = se.files.openOutFile(args.record, "a" if args.append else "w")
    if args.outfile == "stdout":
        outFile = sys.stdout
    else:
        outFile = se.files.openOutFile(args.outfile, "a" if args.append else "w")

    # figure out what to do based on the mode of operation
    if mode.passiveMode:  # only reading from file or serial device
        # read until eof then terminate
        readData(args, mode, dataFile, recFile, outFile, keyStr)
    else:  # reading and writing to network or serial device
        if args.commands:  # commands were specified
            # perform commands then terminate
            doCommands(args, mode, dataFile, recFile, outFile)
        else:  # interacting over network or RS485
            # start a separate thread for reading
            readThread = threading.Thread(
                name=READ_THREAD_NAME,
                target=readData,
                args=(args, mode, dataFile, recFile, outFile, keyStr))
            readThread.daemon = True
            readThread.start()
            logger.info("starting %s", READ_THREAD_NAME)
            if args.master:  # send RS485 master commands
                startMaster(args=(dataFile, recFile, args.slaves))
            # wait for termination
            block()
            
    # cleanup
    se.files.closeData(dataFile, mode.networkDevice)
    se.files.closeOutFiles(recFile, outFile)
