# SolarEdge input data and file management

import serial
import sys
import socket
from seConf import *
from seNetwork import *

#servers = []

#for port in portlist:
#    ds = ("0.0.0.0", port)

#    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#    server.bind(ds)
#    server.listen(1)

#    servers.append(server)

#while True:
#    # Wait for any of the listening servers to get a client
#    # connection attempt
#    readable,_,_ = select.select(servers, [], [])
#    ready_server = readable[0]

#    connection, address = ready_server.accept()


# open data socket and wait for connection from inverter
def openDataSocket():
    try:
        # open a socket and wait for a connection
        dataSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dataSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dataSocket.bind(("", sePort))
        dataSocket.listen(0)
        debug("debugFiles", "waiting for connection")
        (clientSocket, addr) = dataSocket.accept()
        dataSocket.close()
        debug("debugFiles", "connection from", addr[0] + ":" + str(addr[1]))
        # set a timeout so lost connection can be detected
        clientSocket.settimeout(socketTimeout)
        return clientSocket.makefile("rwb")
    except:
        terminate(1, "Unable to open data socket")


# open serial device
def openSerial(inFileName):
    try:
        return serial.Serial(inFileName, baudrate=baudRate)
    except:
        terminate(1, "Unable to open " + inFileName)


def openInFile(inFileName):
    try:
        if inFileName == "stdin":
            return sys.stdin
        else:
            # Explicitly specify mode rb to keep windows happy!
            return open(inFileName, 'rb')
    except:
        terminate(1, "Unable to open " + inFileName)


# open the specified data source
def openData(inFileName):
    if debugFiles: log("opening", inFileName)
    if networkDevice:
        if networkSvcs:
            # start network services
            startDhcp()
            startDns()
        return openDataSocket()
    elif serialDevice:
        return openSerial(inFileName)
    else:
        return openInFile(inFileName)


# close the data source
def closeData(dataFile):
    debug("debugFiles", "closing", dataFile.name)
    if networkDevice:
        dataFile._sock.close()
    dataFile.close()


# open in output file if it is specified
def openOutFile(fileName, writeMode="w"):
    if fileName != "":
        try:
            return open(fileName, writeMode)
            debug("debugFiles", "writing", fileName)
        except:
            terminate(1, "Unable to open " + fileName)
    else:
        return None


# open the output files
def openOutFiles(recFileName, outFileName):
    recFile = openOutFile(recFileName, writeMode)
    if outFileName == "stdout":
        outFile = sys.stdout
    else:
        outFile = openOutFile(outFileName, writeMode)
    return (recFile, outFile)


# close output files
def closeOutFiles(recFile, outFile):
    if recFile:
        debug("debugFiles", "closing", recFile.name)
        recFile.close()
    if outFile:
        debug("debugFiles", "closing", outFile.name)
        outFile.close()
