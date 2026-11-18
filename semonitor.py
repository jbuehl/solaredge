#!/usr/bin/env python3

"""
SolarEdge inverter performance monitoring using the SolarEdge protocol.

Reads SolarEdge messages from a file or serial device, extracts the
performance data, and can send commands and act as an RS485 master.
"""

import dataclasses
import logging
import struct
import sys
import threading
import time
from pathlib import Path

import se.commands
import se.data
import se.env
import se.files
import se.logutils
import se.msg

logger = logging.getLogger(__name__)

# action parameters
COMMAND_DELAY = 2
READ_THREAD_NAME = "read thread"
MASTER_THREAD_NAME = "master thread"
MASTER_MSG_INTERVAL = 5
MASTER_MSG_TIMEOUT = 10
MASTER_ADDR = 0xFFFFFFFE
SEQ_FILE_NAME = "seseq.txt"
MAX_SEQ = 0xFFFF  # the sequence number wraps after this
PROT_CMD_SERVER_KEY = 0x0503  # the message with the encryption key

# global variables
thread_lock = threading.Lock()  # lock to synchronize reads and writes
master_event = threading.Event()  # event to signal RS485 master release


@dataclasses.dataclass
class Files:
    """The files semonitor reads from and writes to."""

    data: object  # the serial device or file to read the data from
    rec: object  # the file to record the data to, if any
    out: object  # the file to write the JSON to


def terminate(code=0, msg=b""):
    """Log msg, at info level for code 0 or error level otherwise, and exit."""
    if code == 0:
        logger.info(msg)
    else:
        logger.error(msg)
    sys.exit(code)


def read_data(args, mode, state, files):
    """
    Read and process messages until the end of the input.

    Messages that are all zeros are ignored. A message that fails to
    process is logged and re-raised only if the xerror option is set.
    """
    eof = False
    if mode.passiveMode:
        # skip data until the start of the first complete message
        (msg, eof) = se.msg.read_msg(files.data, files.rec, mode, state)
    while not eof:
        (msg, eof) = se.msg.read_msg(files.data, files.rec, mode, state)
        if eof:  # end of file
            logger.info("End of file")
        if msg == b"\x00" * len(msg):  # ignore messages containing all zeros
            logger.data(msg)
        else:
            with thread_lock:
                se.logutils.set_state(state, "threadLock", value=True)
                try:
                    process_msg(msg, mode, state, files)
                except Exception as ex:
                    logger.info("Failed to parse message: %s", ex)
                    for line in se.logutils.format_data(msg):
                        logger.data(line)
                    if args.xerror:
                        raise
                se.logutils.set_state(state, "threadLock", value=False)
    return


def process_msg(msg, mode, state, files):
    """
    Parse a received message and act on it.

    Performance data is written to the output file, and in master mode a reply
    is sent when one is due.
    """
    # parse the message
    (msg_seq, from_addr, to_addr, function, data) = se.msg.parse_msg(msg)
    if function == 0:
        # message could not be processed
        logger.data("Ignoring this message")
        for line in se.logutils.format_data(data):
            logger.data(line)
    else:
        msg_data = se.data.parse_data(function, data)
        if (
            function == se.commands.PROT_CMD_SERVER_POST_DATA and data
        ):  # performance data
            # write performance data to output file
            se.data.write_data(msg_data, files.out)
        if mode.masterMode:  # send reply
            (reply_function, reply_data) = master_reply(function, state)
            if reply_function:
                msg = se.msg.format_msg(
                    msg_seq, to_addr, from_addr, reply_function, reply_data
                )
                se.msg.send_msg(files.data, msg, files.rec)


def master_reply(function, state):
    """
    Return the RS485 master's reply to a message.

    Acknowledges data and key messages, answers time requests with the
    current GMT time, and releases the bus on a grant acknowledgment.

    Returns:
        A tuple (function, data) of the reply. The function is b"" when no
        reply is needed.
    """
    if function in (se.commands.PROT_CMD_SERVER_POST_DATA, PROT_CMD_SERVER_KEY):
        # send ack
        return (se.commands.PROT_RESP_ACK, b"")
    if function == se.commands.PROT_CMD_SERVER_GET_GMT:  # time request
        # set time
        return (
            se.commands.PROT_RESP_SERVER_GMT,
            se.data.format_time(
                int(time.time()),
                (time.localtime().tm_hour - time.gmtime().tm_hour) * 60 * 60,
            ),
        )
    if function == se.commands.PROT_RESP_POLESTAR_MASTER_GRANT_ACK:
        # RS485 master release
        master_event.set()
        se.logutils.set_state(state, "masterEvent", master_event.is_set())
    return (b"", b"")


def master_commands(state, data_file, rec_file, slave_addrs):
    """
    Run the RS485 master loop, granting the bus to each slave in turn.

    Runs forever, pausing MASTER_MSG_INTERVAL seconds after each round.
    """
    se.logutils.set_state(state, "masterThread", value=True)
    while True:
        for slave_addr in slave_addrs:
            master_grant(state, data_file, rec_file, slave_addr)
        time.sleep(MASTER_MSG_INTERVAL)
    se.logutils.set_state(state, "masterThread", value=False)


def master_grant(state, data_file, rec_file, slave_addr):
    """
    Grant the RS485 bus to a slave and wait for it to release the bus.

    The wait ends when the slave acknowledges the grant or when
    MASTER_MSG_TIMEOUT seconds have passed.
    """
    with thread_lock:
        se.logutils.set_state(state, "threadLock", value=True)
        # grant control of the bus to the slave
        se.msg.send_msg(
            data_file,
            se.msg.format_msg(
                next_seq(),
                MASTER_ADDR,
                int(slave_addr, 16),
                se.commands.PROT_CMD_POLESTAR_MASTER_GRANT,
            ),
            rec_file,
        )
        se.logutils.set_state(state, "threadLock", value=False)

    def master_timer_expire():
        logger.debug("RS485 master ack timeout")
        master_event.set()
        se.logutils.set_state(state, "masterEvent", master_event.is_set())
        se.logutils.set_state(state, "masterTimer", value=False)

    # start a timeout to release the bus if the slave doesn't respond
    master_timer = threading.Timer(MASTER_MSG_TIMEOUT, master_timer_expire)
    master_timer.start()
    se.logutils.set_state(state, "masterTimer", value=True)
    # wait for slave to release the bus
    master_event.clear()
    se.logutils.set_state(state, "masterEvent", master_event.is_set())
    master_event.wait()
    se.logutils.set_state(state, "masterEvent", master_event.is_set())
    # cancel the timeout
    master_timer.cancel()
    se.logutils.set_state(state, "masterTimer", value=False)


def do_commands(args, mode, state, files):
    """
    Send each command to the slave, wait for its response and record it.

    Responses are written to the output file, with a pause between commands.
    """
    for command in args.commands:
        # format the command parameters
        function = int(command[0], 16)
        struct_fmt = "<" + "".join(c[0] for c in command[1:])
        params = [int(p[1:], 16) for p in command[1:]]
        seq = next_seq()
        # send the command
        se.msg.send_msg(
            files.data,
            se.msg.format_msg(
                seq,
                MASTER_ADDR,
                int(args.slaves[0], 16),
                function,
                struct.pack(struct_fmt, *tuple(params)),
            ),
            files.rec,
        )
        if mode.masterMode:  # send RS485 master command
            # grant control of the bus to the slave
            master_grant(state, files.data, files.rec, args.slaves[0])
        # wait for the response to the command
        (msg, _eof) = se.msg.read_msg(files.data, files.rec, mode, state)
        (_msg_seq, _from_addr, _to_addr, response, data) = se.msg.parse_msg(msg)
        msg_data = se.data.parse_data(response, data)
        # write response to output file
        se.data.write_data(
            {
                "command": function,
                "response": response,
                "sequence": seq,
                "data": msg_data,
            },
            files.out,
        )
        # wait a bit before sending the next one
        time.sleep(COMMAND_DELAY)


def start_master(args):
    """Start the daemon thread that sends the RS485 master commands."""
    # start a thread to send RS485 master commands
    master_thread = threading.Thread(
        name=MASTER_THREAD_NAME, target=master_commands, args=args
    )
    master_thread.daemon = True
    master_thread.start()
    logger.info("starting %s", MASTER_THREAD_NAME)


def block(state):
    """Sleep until a keyboard interrupt, then dump the state."""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        se.logutils.dump_state(state)


def next_seq():
    """
    Return the next message sequence number and store it in the sequence file.

    The number wraps to 1 after MAX_SEQ. It starts at 1 if the file is
    missing or unreadable.
    """
    try:
        with Path(SEQ_FILE_NAME).open() as seq_file:
            seq = int(seq_file.read().rstrip("\n"))
        seq += 1
        if seq > MAX_SEQ:
            seq = 1
    except OSError:
        seq = 1
    with Path(SEQ_FILE_NAME).open("w") as seq_file:
        seq_file.write(str(seq) + "\n")
    return seq


if __name__ == "__main__":
    # create the state variables with timestamps
    state = {}
    se.logutils.set_state(state, "readThread", value=False)
    se.logutils.set_state(state, "masterThread", value=False)
    se.logutils.set_state(state, "masterTimer", value=False)
    se.logutils.set_state(state, "threadLock", value=False)
    se.logutils.set_state(state, "masterEvent", value=False)

    # get the command line arguments and run mode
    (args, mode) = se.env.get_args()

    # open the specified data source
    logger.info("opening %s", args.datasource)
    if mode.serialDevice:
        data_file = se.files.open_serial(args.datasource, args.baudrate)
    else:
        data_file = se.files.open_in_file(args.datasource)

    # open the output files
    rec_file = se.files.open_out_file(
        args.record, "ab" if args.append else "wb"
    )
    if args.outfile == "stdout":
        out_file = sys.stdout.buffer
    else:
        out_file = se.files.open_out_file(
            args.outfile, "ab" if args.append else "wb"
        )

    files = Files(data_file, rec_file, out_file)

    # figure out what to do based on the mode of operation
    if mode.passiveMode:  # only reading from file or serial device
        # read until eof then terminate
        read_data(args, mode, state, files)
    # reading and writing to a serial device
    elif args.commands:  # commands were specified
        # perform commands then terminate
        do_commands(args, mode, state, files)
    else:  # interacting over RS232 or RS485
        # start a separate thread for reading
        read_thread = threading.Thread(
            name=READ_THREAD_NAME,
            target=read_data,
            args=(args, mode, state, files),
        )
        read_thread.daemon = True
        read_thread.start()
        logger.info("starting %s", READ_THREAD_NAME)
        if args.master:  # send RS485 master commands
            start_master(args=(state, data_file, rec_file, args.slaves))
        # wait for termination
        block(state)

    # cleanup
    se.files.close_data(data_file)
    se.files.close_out_files(rec_file, out_file)
