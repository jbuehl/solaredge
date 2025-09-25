#!/usr/bin/env python3

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
import logging
from builtins import bytes

logger = logging.getLogger(__name__)

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
def terminate(code=0, msg=b""):
    if code == 0:
        logger.info(msg)
    else:
        logger.error(msg)
    sys.exit(code)

# process the input data
def readData(args, mode, state, dataFile, recFile, outFile):
    eof = False
    updateBuf = list(b"\x00" * UPDATE_SIZE) if args.updatefile else []
    if mode.passiveMode:
        # skip data until the start of the first complete message
        (msg, eof) = se.msg.readMsg(dataFile, recFile, mode, state)
    while not eof:
        (msg, eof) = se.msg.readMsg(dataFile, recFile, mode, state)
        if eof:  # end of file
            logger.info("End of file")
            # eof from network means connection was broken, wait for a reconnect and continue
            if mode.networkDevice:
                se.files.closeData(dataFile, True)
                dataFile = se.files.openDataSocket(args.ports)
                eof = False
        if msg == b"\x00" * len(msg):  # ignore messages containing all zeros
            logger.data(msg)
        else:
            with threadLock:
                se.logutils.setState(state, "threadLock", True)
                try:
                    processMsg(msg, args, mode, state, dataFile, recFile, outFile, updateBuf)
                except Exception as ex:
                    logger.info("Failed to parse message: "+str(ex))
                    for l in se.logutils.format_data(msg):
                        logger.data(l)
                    if args.xerror:
                        raise
                se.logutils.setState(state, "threadLock", False)
    # all finished
    if args.updatefile:  # write the firmware update file
        writeUpdate(updateBuf, args.updatefile)
    return

# process a received message
def processMsg(msg, args, mode, state, dataFile, recFile, outFile, updateBuf):
    # parse the message
    (msgSeq, fromAddr, toAddr, function, data) = se.msg.parseMsg(msg)
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
            replyFunction = b""
            if function == se.commands.PROT_CMD_SERVER_POST_DATA:  # performance data
                # send ack
                replyFunction = se.commands.PROT_RESP_ACK
                replyData = b""
            elif function == 0x0503:  # encryption key
                # send ack
                replyFunction = se.commands.PROT_RESP_ACK
                replyData = b""
            elif function == se.commands.PROT_CMD_SERVER_GET_GMT:  # time request
                # set time
                replyFunction = se.commands.PROT_RESP_SERVER_GMT
                replyData = se.data.formatTime(int(time.time()),
                    (time.localtime().tm_hour - time.gmtime().tm_hour) * 60 * 60)
            elif function == se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK:  # RS485 master release
                masterEvent.set()
                se.logutils.setState(state, "masterEvent", masterEvent.is_set())
            if replyFunction:
                msg = se.msg.formatMsg(msgSeq, toAddr, fromAddr, replyFunction, replyData)
                se.msg.sendMsg(dataFile, msg, recFile)

# write firmware image to file
def writeUpdate(updateBuf, updateFileName):
    updateBuf = b"".join(updateBuf)
    logger.info("writing %s", updateFileName)
    with open(updateFileName, "wb") as updateFile:
        updateFile.write(updateBuf)

# RS485 master commands thread
def masterCommands(state, dataFile, recFile, slaveAddrs):
    se.logutils.setState(state, "masterThread", True)
    while True:
        for slaveAddr in slaveAddrs:
            masterGrant(state, dataFile, recFile, slaveAddr)
        time.sleep(MASTER_MSG_INTERVAL)
    se.logutils.setState(state, "masterThread", False)

# send RS485 master grant command and wait for an ACK
def masterGrant(state, dataFile, recFile, slaveAddr):
    with threadLock:
        se.logutils.setState(state, "threadLock", True)
        # grant control of the bus to the slave
        se.msg.sendMsg(dataFile,
                    se.msg.formatMsg(nextSeq(), MASTER_ADDR, int(slaveAddr, 16),
                          se.commands.PROT_CMD_POLESTAR_MASTER_GRANT), recFile)
        se.logutils.setState(state, "threadLock", False)

    def masterTimerExpire():
        logger.debug("RS485 master ack timeout")
        masterEvent.set()
        se.logutils.setState(state, "masterEvent", masterEvent.is_set())
        se.logutils.setState(state, "masterTimer", False)

    # start a timeout to release the bus if the slave doesn't respond
    masterTimer = threading.Timer(MASTER_MSG_TIMEOUT, masterTimerExpire)
    masterTimer.start()
    se.logutils.setState(state, "masterTimer", True)
    # wait for slave to release the bus
    masterEvent.clear()
    se.logutils.setState(state, "masterEvent", masterEvent.is_set())
    masterEvent.wait()
    se.logutils.setState(state, "masterEvent", masterEvent.is_set())
    # cancel the timeout
    masterTimer.cancel()
    se.logutils.setState(state, "masterTimer", False)

# perform the specified commands
def doCommands(args, mode, state, dataFile, recFile, outFile):
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
        if mode.masterMode:  # send RS485 master command
            # grant control of the bus to the slave
            masterGrant(state, dataFile, recFile, args.slaves[0])
        # wait for the response to the command
        (msg, eof) = se.msg.readMsg(dataFile, recFile, mode, state)
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
def block(state):
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        se.logutils.dumpState(state)

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
    # create the state variables with timestamps
    state = {}
    se.logutils.setState(state, "readThread", False)
    se.logutils.setState(state, "masterThread", False)
    se.logutils.setState(state, "masterTimer", False)
    se.logutils.setState(state, "threadLock", False)
    se.logutils.setState(state, "masterEvent", False)

    # get the command line arguments and run mode
    (args, mode) = se.env.getArgs()

    # open the specified data source
    logger.info("opening %s", args.datasource)
    if args.datasource == "network":
        dataFile =  se.files.openDataSocket(args.ports)
    elif mode.serialDevice:
        dataFile =  se.files.openSerial(args.datasource, args.baudrate)
    else:
        dataFile =  se.files.openInFile(args.datasource)

    # open the output files
    recFile = se.files.openOutFile(args.record, "ab" if args.append else "wb")
    if args.outfile == "stdout":
        if sys.version_info >= (3,0):
            outFile = sys.stdout.buffer
        else:
            outFile = sys.stdout
    else:
        outFile = se.files.openOutFile(args.outfile, "ab" if args.append else "wb")

    # figure out what to do based on the mode of operation
    if mode.passiveMode:  # only reading from file or serial device
        # read until eof then terminate
        readData(args, mode, state, dataFile, recFile, outFile)
    else:  # reading and writing to network or serial device
        if args.commands:  # commands were specified
            # perform commands then terminate
            doCommands(args, mode, state, dataFile, recFile, outFile)
        else:  # interacting over network or RS485
            # start a separate thread for reading
            readThread = threading.Thread(
                name=READ_THREAD_NAME,
                target=readData,
                args=(args, mode, state, dataFile, recFile, outFile))
            readThread.daemon = True
            readThread.start()
            logger.info("starting %s", READ_THREAD_NAME)
            if args.master:  # send RS485 master commands
                startMaster(args=(state, dataFile, recFile, args.slaves))
            # wait for termination
            block(state)

    # cleanup
    se.files.closeData(dataFile, mode.networkDevice)
    se.files.closeOutFiles(recFile, outFile)
