# SolarEdge input data and file management

import serial
import sys
import logging
import se.logutils

logger = logging.getLogger(__name__)

# open serial device
def openSerial(inFileName, baudRate):
    return serial.Serial(inFileName, baudrate=baudRate)

def openInFile(inFileName):
    if inFileName == "stdin":
        if sys.version_info >= (3,0):
            return sys.stdin.buffer
        else:
            return sys.stdin
    else:
        # Explicitly specify mode rb to keep Windows happy!
        return open(inFileName, 'rb')

# close the data source
def closeData(dataFile):
    logger.info("closing %s", dataFile.name)
    dataFile.close()

# open the output file if it is specified
def openOutFile(fileName, writeMode="wb"):
    if fileName:
        return open(fileName, writeMode)

# close output files
def closeOutFiles(recFile, outFile):
    if recFile:
        logger.info("closing %s", recFile.name)
        recFile.close()
    if outFile:
        logger.info("closing %s", outFile.name)
        outFile.close()
