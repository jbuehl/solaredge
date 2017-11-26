# SolarEdge command line argument parsing and validation

import sys
import netifaces
import serial.tools.list_ports
import re
import argparse
from collections import namedtuple
import logging
import se.logutils

logger = logging.getLogger(__name__)

# run environment that is derived from the arguments that defines how the program will behave
RunMode = namedtuple("RunMode", ("serialDevice",  # boolean
                                 "networkDevice", # boolean
                                 "serialType",    # serial device type: "2" or "4" 
                                 "passiveMode",   # boolean 
                                 "masterMode",    # boolean
                                 "following",     # boolean
                                 ))

def error(msg):
    logger.error(msg)
    return True
    
def getArgs():
    errors = False

    def validated_commands(command_str):
        commands = []
        for c in command_str.split("/"):
            if not re.match(r"^[0-9a-fA-F]+(,[bhlBHL][0-9a-fA-F]+)*$", c):
                raise argparse.ArgumentTypeError("Invalid command: {}".format(c))
            commands.append(c.split(","))
        return commands

    parser = argparse.ArgumentParser(description='Parse Solaredge data to extract inverter and optimizer telemetry', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
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
    parser.add_argument("-s", dest="slaves", type=lambda s: [int(x.strip(), 16) for x in s.split(",")], default=[], 
        help="comma delimited list of SolarEdge slave inverter IDs")
    parser.add_argument("-t", dest="type", choices=["2","4","n"], help="serial data source type (2=RS232, 4=RS485, n=network)")
    parser.add_argument("-u", dest="updatefile", type=argparse.FileType('w'), help="file to write firmware update to (experimental)")
    parser.add_argument("-v", dest="verbose", action="count", default=0, help="verbose output")
    parser.add_argument("-x", dest="xerror", action="store_true", default=False, help="halt on data exception")
    parser.add_argument("datasource", default="stdin", nargs='?', help="Input filename or serial port")

    args = parser.parse_args()

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
    serialDevice = False
    networkDevice = False
    
    if args.datasource == "-":
        args.datasource = "stdin"
        passiveMode = True
    else:
        # figure out the list of valid serial ports on this server
        # this is either a list of tuples or ListPortInfo objects
        serial_ports = serial.tools.list_ports.comports()
        serial_port_names = map(lambda p: p.device if isinstance(p, 
                                serial.tools.list_ports_common.ListPortInfo) else p[0], serial_ports)
        serialDevice = args.datasource in serial_port_names
        passiveMode = True

    if args.type in ["2", "4"] and not serialDevice:
        errors = error(args.datasource+" is not a valid serial device")
        errors = error("Input device types 2 and 4 are only valid for a serial device")
    if args.type == "n":
        if args.datasource != "":
            errors = error("Input file cannot be specified for network mode")
        args.datasource = "network"
        networkDevice = True
        passiveMode = False

    # get network interface parameters
    if args.interface:
        args.datasource = "network"
        networkDevice = True
        passiveMode = False

    # serial device validation
    if serialDevice:
        serialDevice = True
        args.following = True
        if args.type == "2":
            passiveMode = False
        elif args.type != "4":
            errors = error("Input device type 2 or 4 must be specified for serial device")

    # master mode validation
    if args.master:
        passiveMode = False
        if args.type != "4":
            errors = error("Master mode only allowed with RS485 serial device")
        if len(args.slaves) < 1:
            errors = error("At least one slave address must be specified for master mode")
    else:
        passiveMode = True

    # command mode validation
    if args.commands:
        passiveMode = False
        if len(args.slaves) != 1:
            errors = error("Exactly one slave address must be specified for command mode")

    # print out the arguments and option
    if errors:
        parser.print_usage()
    else:
        for k,v in vars(args).iteritems():
            if k == "slaves":
                v = map(hex, v)
            logger.info("%s: %s", k, v)

    return (errors, args, 
        RunMode(serialDevice, networkDevice, args.type, passiveMode, args.master, args.follow))
    
