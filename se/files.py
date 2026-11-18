"""SolarEdge input data and file management."""

import logging
import sys
from pathlib import Path

import serial

logger = logging.getLogger(__name__)


def openSerial(in_file_name, baud_rate):
    """Open the serial device in_file_name at baud_rate."""
    return serial.Serial(in_file_name, baudrate=baud_rate)


def openInFile(in_file_name):
    """
    Open the data source for reading in binary mode.

    The name "stdin" gives the binary buffer of standard input instead.
    """
    if in_file_name == "stdin":
        return sys.stdin.buffer
    # Explicitly specify mode rb to keep Windows happy!
    return Path(in_file_name).open("rb")


def closeData(data_file):
    """Close the data source, and log its name."""
    logger.info("closing %s", data_file.name)
    data_file.close()


def openOutFile(file_name, write_mode="wb"):
    """Open the output file in write_mode, or return None if no name is given."""
    if file_name:
        return Path(file_name).open(write_mode)
    return None


def closeOutFiles(rec_file, out_file):
    """Close the record and output files, logging the name of each one closed."""
    if rec_file:
        logger.info("closing %s", rec_file.name)
        rec_file.close()
    if out_file:
        logger.info("closing %s", out_file.name)
        out_file.close()
