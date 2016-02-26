# SolarEdge serial I/O

import serial
import sys

from seConf import *

def openSerial():
    if debugFiles: log("opening", inFileName)
    if inFileName == "stdin":
        inFile = sys.stdin
    elif inFileName[0:len(serialFileName)] == serialFileName:
        inFile = serial.Serial(inFileName, baudrate=baudRate)
    else:
        try:
            inFile = open(inFileName)
            if masterMode:
                terminate(1, "Master mode not allowed with file input")
        except:
            terminate(1, "Unable to open "+inFileName)
    return inFile

