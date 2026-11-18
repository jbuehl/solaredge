"""SolarEdge input data and file management."""

import logging
import sys
from pathlib import Path

import serial

logger = logging.getLogger(__name__)


def openSerial(inFileName, baudRate):
    """Open the serial device inFileName at baudRate."""
    return serial.Serial(inFileName, baudrate=baudRate)


def openInFile(inFileName):
    """
    Open the data source for reading in binary mode.

    The name "stdin" gives the binary buffer of standard input instead.
    """
    if inFileName == "stdin":
        return sys.stdin.buffer
    # Explicitly specify mode rb to keep Windows happy!
    return Path(inFileName).open("rb")


def closeData(dataFile):
    """Close the data source, and log its name."""
    logger.info("closing %s", dataFile.name)
    dataFile.close()


def openOutFile(fileName, writeMode="wb"):
    """Open the output file in writeMode, or return None if no name is given."""
    if fileName:
        return Path(fileName).open(writeMode)
    return None


def closeOutFiles(recFile, outFile):
    """Close the record and output files, logging the name of each one closed."""
    if recFile:
        logger.info("closing %s", recFile.name)
        recFile.close()
    if outFile:
        logger.info("closing %s", outFile.name)
        outFile.close()
