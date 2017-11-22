#!/usr/bin/env python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

import time
import threading
import getopt
import sys
from seConf import *
from seFiles import *
from seMsg import *
from seData import *
from seCommands import *
import logging

logger = logging.getLogger(__name__)

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
            logger.message(msg)
        else:
            with threadLock:
                try:
                    processMsg(msg, dataFile, recFile, outFile)
                except Exception as ex:
                    logger.info("Exception", exc_info=ex)
                    if haltOnException:
                        for l in format_data(msg):
                            logger.message(l)
                        raise


# process a received message
def processMsg(msg, dataFile, recFile, outFile):
    # parse the message
    (msgSeq, fromAddr, toAddr, function, data) = parseMsg(msg)
    if function == 0:
        # message could not be processed
        logger.message("Ignoring this message")
        for l in format_data(data):
            logger.message(l)
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
    logger.debug("writing %s", updateFileName)
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
                logger.debug("RS485 master ack timeout")
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
    logger.debug("starting %s", masterThreadName)

# get next sequence number
def nextSeq():
    try:
        with open(seqFileName) as seqFile:
            seq = int(seqFile.read().rstrip("\n"))
        seq += 1
        if seq > 65535:
            seq = 1
    except:
        seq = 1
    with open(seqFileName, "w") as seqFile:
        seqFile.write(str(seq) + "\n")
    return seq


# block while waiting for a keyboard interrupt
def waitForEnd():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # commit suicide
        os.kill(os.getpid(), signal.SIGKILL)
        return False


# parse and validate the commands specified in the -c option
def parseCommands(opt):
    try:
        commands = [command.split(",") for command in opt.split("/")]
        for command in commands:
            try:
                # validate the command function
                v = int(command[0], 16)
                # validate command parameters
                for p in command[1:]:
                    # validate data type
                    if p[0] not in "bhlBHL":
                        log(" ".join(c for c in command))
                        terminate(1, "Invalid data type " + p[0])
                    # validate parameter value
                    v = int(p[1:], 16)
            except ValueError:
                log(" ".join(c for c in command))
                terminate(1, "Invalid numeric value")
    except:
        terminate(1, "Error parsing commands")
    return commands


if __name__ == "__main__":
    # figure out the list of valid serial ports on this server
    try:
        serialPortNames = []
        serialPorts = serial.tools.list_ports.comports()
        # this is either a list of tuples or ListPortInfo objects
        if isinstance(serialPorts[0], tuple):
            for serialPort in serialPorts:
                serialPortNames.append(serialPort[0])
        elif isinstance(serialPorts[0],
                        serial.tools.list_ports_common.ListPortInfo):
            for serialPort in serialPorts:
                serialPortNames.append(serialPort.device)
    except:
        pass

    # get program arguments and options
    (opts, args) = getopt.getopt(sys.argv[1:], "ab:c:d:fk:mn:o:p:r:s:t:u:vx")
    # arguments

    inFileName = args[0]
    if inFileName == "-":
        inFileName = "stdin"
    elif inFileName in serialPortNames:
        serialDevice = True
    else:
        inFileName = "stdin"
        following = True

    v_level = 0

    # options
    for opt in opts:
        if opt[0] == "-a":
            writeMode = "a"
        elif opt[0] == "-b":
            baudRate = opt[1]
        elif opt[0] == "-c":
            commandStr = opt[1]
        elif opt[0] == "-d":
            debugFileName = opt[1]
        elif opt[0] == "-f":
            following = True
        elif opt[0] == "-k":
            keyFileName = opt[1]
        elif opt[0] == "-m":
            masterMode = True
        elif opt[0] == "-n":
            netInterface = opt[1]
        elif opt[0] == "-o":
            outFileName = opt[1]
        elif opt[0] == "-p":
            sePort = int(opt[1])
        elif opt[0] == "-r":
            recFileName = opt[1]
        elif opt[0] == "-s":
            slaveAddrs = opt[1].split(",")
        elif opt[0] == "-t":
            inputType = opt[1]
        elif opt[0] == "-u":
            updateFileName = opt[1]
        elif opt[0] == "-v":
            v_level += 1
        elif opt[0] == "-x":
            haltOnException = True
        else:
            terminate(1, "Unknown option " + opt[0])

    # configure logging
    
    if debugFileName == "syslog":
        handler = logging.SysLogHandler()
    elif debugFileName == "stderr":
        handler = logging.StreamHandler(stream=sys.stderr)
    elif debugFileName == "stdout":
        handler = logging.StreamHandler(stream=sys.stdout)
    elif debugFileName:
        handler = logging.FileHandler(debugFileName, mode=writeMode)

    level = {
            1: logging.DEBUG,
            2: LOG_LEVEL_MSG,
            3: LOG_LEVEL_RAW,
            }.get(min(v_level, 3), logging.INFO)

    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%b %d %H:%M:%S"))

    # configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # validate input type
    if inputType in ["2", "4"]:
        if not serialDevice:
            terminate(
                1, "Input device types 2 and 4 are only valid for a serial device")
    elif inputType == "n":
        if inFileName != "stdin":
            terminate(1, "Input file cannot be specified for network mode")
        networkDevice = True
        inFileName = "network"
    elif inputType != "":
        terminate(1, "Invalid input type " + inputType)

    # get network interface parameters
    if netInterface != "":
        networkDevice = True
        inFileName = "network"
        passiveMode = False
        try:
            netInterfaceParams = netifaces.ifaddresses(netInterface)[2][0]
            ipAddr = netInterfaceParams["addr"]
            broadcastAddr = netInterfaceParams["broadcast"]
            subnetMask = netInterfaceParams["netmask"]
            networkSvcs = True
        except:
            raise
            terminate(1, "network interface is not available")

    # serial device validation
    if serialDevice:
        following = True
        if inputType == "2":
            passiveMode = False
        elif inputType != "4":
            terminate(
                1, "Input device type 2 or 4 must be specified for serial device")

    # master mode validation
    if masterMode:
        passiveMode = False
        if inputType != "4":
            terminate(1, "Master mode only allowed with RS485 serial device")
        if len(slaveAddrs) < 1:
            terminate(
                1, "At least one slave address must be specified for master mode")

    # command mode validation
    if commandStr != "":
        commands = parseCommands(commandStr)
        commandAction = True
        passiveMode = False
        if len(slaveAddrs) != 1:
            terminate(
                1, "Exactly one slave address must be specified for command mode")

    # get encryption key
    if keyFileName != "":
        with open(keyFileName) as keyFile:
            keyStr = keyFile.read().rstrip("\n")

    # print out the arguments and options
    # debug parameters
    logger.info("debugFileName: %s", debugFileName)
    logger.info("haltOnException: %s", haltOnException)
    # input parameters
    logger.info("inFileName: %s", inFileName)
    if inputType != "":
        logger.info("inputType: %s", inputType)
    logger.info("serialDevice: %s", serialDevice)
    if serialDevice:
        logger.info("    baudRate: %s", baudRate)
    logger.info("networkDevice: %s", networkDevice)
    logger.info("sePort: %s", sePort)
    logger.info("networkSvcs: %s", networkSvcs)
    if networkSvcs:
        logger.info("netInterface %s", netInterface)
        logger.info("    ipAddr %s", ipAddr)
        logger.info("    subnetMask %s", subnetMask)
        logger.info("    broadcastAddr %s", broadcastAddr)
    logger.info("following: %s", following)
    # action parameters
    logger.info("passiveMode: %s", passiveMode)
    logger.info("commandAction: %s", commandAction)
    if commandAction:
        for command in commands:
            logger.info("    command: %s", " ".join(c for c in command))
    logger.info("masterMode: %s", masterMode)
    if masterMode or commandAction:
        logger.info("slaveAddrs: %s", ",".join(slaveAddr for slaveAddr in slaveAddrs))
    # output parameters
    logger.info("outFileName: %s", outFileName)
    if recFileName != "":
        logger.info("recFileName: %s", recFileName)
    logger.info("append: %s", writeMode)
    if keyFileName != "":
        logger.info("keyFileName: %s", keyFileName)
        logger.info("key: %s", keyStr)
    if updateFileName != "":
        logger.info("updateFileName: %s", updateFileName)

    # initialization
    dataFile = openData(inFileName, networkDevice, serialDevice)
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
            logger.debug("starting %s", readThreadName)
            if masterMode:  # send RS485 master commands
                startMaster(args=(dataFile, recFile))
            # wait for termination
            running = waitForEnd()
    # cleanup
    closeData(dataFile)
    closeOutFiles(recFile, outFile)
