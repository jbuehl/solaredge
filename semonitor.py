#!/usr/bin/env python

# SolarEdge inverter performance monitoring using the SolarEdge protocol

import time
import threading
import sys
import struct
import netifaces
import serial.tools.list_ports
import se.logutils
import se.files
import se.msg
import se.data
import se.commands
import se.network
import logging
import logging.handlers
import re
import argparse

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
def terminate(code=0, msg=""):
    if code == 0:
        logger.info(msg)
    else:
        logger.error(msg)
    sys.exit(code)

# process the input data
def readData(dataFile, recFile, outFile, haltOnDataParsingException, following, inputType, port, passiveMode, updateFileName, keyStr, masterMode):
    updateBuf = list('\x00' * UPDATE_SIZE) if updateFileName else []
    if passiveMode:
        msg = se.msg.readMsg(dataFile, recFile, passiveMode, inputType, following)  # skip data until the start of the first complete message
    while True:
        msg = se.msg.readMsg(dataFile, recFile, passiveMode, inputType, following)
        if msg == "":  # end of file
            # eof from network means connection was broken, wait for a reconnect and continue
            if inputType == "n":
                se.files.closeData(dataFile, True)
                dataFile = se.files.openDataSocket(port)
            else:  # all finished
                if updateFileName:  # write the firmware update file
                    writeUpdate(updateBuf, updateFileName)
                return
        if msg == "\x00" * len(msg):  # ignore messages containing all zeros
            logger.data(msg)
        else:
            with threadLock:
                try:
                    processMsg(msg, dataFile, recFile, outFile, keyStr, updateBuf, inputType, masterMode)
                except:
                    logger.info("Filed to parse message")
                    for l in seLogging.format_data(msg):
                        logger.data(l)
                    if haltOnDataParsingException:
                        raise

# process a received message
def processMsg(msg, dataFile, recFile, outFile, keyStr, updateBuf, inputType, masterMode):
    # parse the message
    (msgSeq, fromAddr, toAddr, function, data) = se.msg.parseMsg(msg, keyStr)
    if function == 0:
        # message could not be processed
        logger.data("Ignoring this message")
        for l in seLogging.format_data(data):
            logger.data(l)
    else:
        msgData = se.data.parseData(function, data)
        if function == se.commands.PROT_CMD_SERVER_POST_DATA and data:  # performance data
            # write performance data to output file
            se.data.writeData(msgData, outFile)
        elif updateBuf and function == se.commands.PROT_CMD_UPGRADE_WRITE:  # firmware update data
            updateBuf[msgData["offset"]:msgData["offset"] + msgData["length"]] = msgData["data"]
        if inputType == "n" or masterMode:  # send reply
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
                logger.info("RS485 master ack timeout")
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
def doCommands(dataFile, commands, recFile, inputType, slaveAddr, passiveMode, keyStr, masterMode, following):
    if masterMode:  # send RS485 master command
        # grant control of the bus to the slave
        se.msg.sendMsg(dataFile,
                se.msg.formatMsg(nextSeq(), MASTER_ADDR, slaveAddr,
                          se.commands.PROT_CMD_POLESTAR_MASTER_GRANT), recFile)
    for command in commands:
        # format the command parameters
        function = int(command[0], 16)
        format = "<" + "".join(c[0] for c in command[1:])
        params = [int(p[1:], 16) for p in command[1:]]
        seq = nextSeq()
        # send the command
        se.msg.sendMsg(dataFile,
                se.msg.formatMsg(seq, MASTER_ADDR, slaveAddr, function,
                          struct.pack(format, *tuple(params))), recFile)
        # wait for the response
        msg = se.msg.readMsg(dataFile, recFile, passiveMode, inputType, following)
        (msgSeq, fromAddr, toAddr, response, data) = se.msg.parseMsg(msg, keyStr)
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
    # figure out the list of valid serial ports on this server
    # this is either a list of tuples or ListPortInfo objects
    serial_ports = serial.tools.list_ports.comports()
    serial_port_names = map(lambda p: p.device if isinstance(p, 
                            serial.tools.list_ports_common.ListPortInfo) else p[0], serial_ports)

    def validated_commands(command_str):
        commands = []
        for c in command_str.split("/"):
            if not re.match(r"^[0-9a-fA-F]+(,[bhlBHL][0-9a-fA-F]+)*$", c):
                raise argparse.ArgumentTypeError("Invalid command: {}".format(c))
            commands.append(c.split(","))
        return commands


    parser = argparse.ArgumentParser(description='Parse Solaredge data to extract inverter and optimizer telemetry', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-a", dest="append", action="store_true", default=False, help="append to output file if the file exists")
    parser.add_argument("-b", dest="baudrate", type=int, default=115200, help="baud rate for serial data source")
    parser.add_argument("-c", dest="commands", type=validated_commands, default=[], help="send the specified command functions")
    parser.add_argument("-d", dest="logfile", default="stderr", help="where to write log messages.  either a file name or one of ['stderr', 'syslog']")
    parser.add_argument("-f", dest="follow", action="store_true", default=False, help="wait for appended data as the input file grows (as in tail -f)")
    parser.add_argument("-k", dest="keyfile", type=argparse.FileType('r'), help="file containing a hex encoded encryption key")
    parser.add_argument("-m", dest="master", action="store_true", default=False, help="function as a RS485 master")
    parser.add_argument("-n", dest="interface", type=netifaces.ifaddresses, help="run DHCP and DNS network services on the specified interface")
    parser.add_argument("-o", dest="outfile", default="stdout", help="write performance data to the specified file in JSON format (default: stdout)")
    parser.add_argument("-p", dest="port", type=int, default=22222, help="port to listen on in network mode")
    parser.add_argument("-r", dest="record", type=argparse.FileType('w'), help="file to record all incoming and outgoing messages to")
    parser.add_argument("-s", dest="slaves", type=lambda s: [int(x.strip(), 16) for x in s.split(",")], default=[], help="comma delimited list of SolarEdge slave inverter IDs")
    parser.add_argument("-t", dest="type", choices=["2","4","n"], help="serial data source type (2=RS232, 4=RS485, n=network)")
    parser.add_argument("-u", dest="update_file", type=argparse.FileType('w'), help="file to write firmwate update to (experimental)")
    parser.add_argument("-v", dest="verbose", action="count", default=0, help="verbose output")
    parser.add_argument("-x", dest="xerror", action="store_true", default=False, help="halt on data exception")
    parser.add_argument("datasource", default="stdin", nargs='?', help="Input filename or serial port")


    args = parser.parse_args()
    if args.datasource == "-":
        args.datasource = "stdin"

    serialDevice = args.datasource in serial_port_names
    passiveMode = True

    # configure logging
    stream_formatter = logging.Formatter("%(message)s")
    file_formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%b %d %H:%M:%S")
    
    if args.logfile == "syslog":
        handler = logging.handlers.SysLogHandler(address="/dev/log")
        handler.setFormatter(stream_formatter)
    elif args.logfile == "stderr":
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(stream_formatter)
    elif args.logfile == "stdout":
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(stream_formatter)
    elif args.logfile:
        handler = logging.FileHandler(args.logfile, mode="a" if args.append else "w")
        handler.setFormatter(file_formatter)

    level = {                               # previously:
            1: logging.INFO,                # -v    debugFiles
            2: logging.DEBUG,               # -vv   debugMsgs
            3: se.logutils.LOG_LEVEL_DATA,  # -vvv  debugData
            4: se.logutils.LOG_LEVEL_RAW,   # -vvvv debugRaw
            }.get(min(args.verbose, 4), logging.ERROR)

    # configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # validate input type
    if args.type in ["2", "4"] and not serialDevice:
        terminate(1, "Input device types 2 and 4 are only valid for a serial device")
    if args.type == "n":
        args.datasource = "network"
        if args.datasource != "stdin":
            terminate(1, "Input file cannot be specified for network mode")

    # get network interface parameters
    if args.interface:
        args.datasource = "network"
        passiveMode = False
        netInterfaceParams = args.interface[2][0]
        ipAddr = netInterfaceParams["addr"]
        broadcastAddr = netInterfaceParams["broadcast"]
        subnetMask = netInterfaceParams["netmask"]

    # serial device validation
    if serialDevice:
        args.following = True
        if args.type == "2":
            passiveMode = False
        elif args.type != "4":
            terminate(1, "Input device type 2 or 4 must be specified for serial device")

    # master mode validation
    if args.master:
        passiveMode = False
        if args.type != "4":
            terminate(1, "Master mode only allowed with RS485 serial device")
        if len(args.slaves) < 1:
            terminate(1, "At least one slave address must be specified for master mode")

    # command mode validation
    if args.commands:
        passiveMode = False
        if len(args.slaves) != 1:
            terminate(1, "Exactly one slave address must be specified for command mode")

    # get encryption key
    keyStr = args.keyfile.read().rstrip("\n") if args.keyfile else None

    # print out the arguments and options
    for k,v in vars(args).iteritems():
        if k == "slaves":
            v = map(hex, v)
        logger.info("%s: %s", k, v)

    # initialization
    # open the specified data source
    logger.info("opening %s", args.datasource)
    if args.datasource == "network":
        if args.interface:
            # start network services
            seNetwork.startDhcp(ipAddr, subnetMask, broadcastAddr)
            seNetwork.startDns(ipAddr)
        dataFile =  se.files.openDataSocket(args.port)
    elif serialDevice:
        dataFile =  se.files.openSerial(args.datasource, args.baudrate)
    else:
        dataFile =  se.files.openInFile(args.datasource)

    # open the output files
    recFile = se.files.openOutFile(args.record, "a" if args.append else "w")
    if args.outfile == "stdout":
        outFile = sys.stdout
    else:
        outFile = se.files.openOutFile(args.outfile, "a" if args.append else "w")

    if passiveMode:  # only reading from file or serial device
        # read until eof then terminate
        readData(dataFile, recFile, outFile, args.xerror, args.follow, args.type, args.port, passiveMode, args.update_file, keyStr, args.master)
    else:  # reading and writing to network or serial device
        if args.commands:  # commands were specified
            # perform commands then terminate
            doCommands(dataFile, args.commands, recFile, args.type, args.slaves[0], passiveMode, keyStr, args.master, args.follow)
        else:  # network or RS485
            # start a thread for reading
            readThread = threading.Thread(
                name=READ_THREAD_NAME,
                target=readData,
                args=(dataFile, recFile, outFile, args.xerror, args.follow, args.type, args.port, passiveMode, args.update_file, keyStr, args.master))
            readThread.daemon = True
            readThread.start()
            logger.info("starting %s", READ_THREAD_NAME)
            if args.master:  # send RS485 master commands
                startMaster(args=(dataFile, recFile, args.slaves))
            # wait for termination
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    # cleanup
    se.files.closeData(dataFile, args.type == "n")
    se.files.closeOutFiles(recFile, outFile)
