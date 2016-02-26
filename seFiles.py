# SolarEdge file management

from seConf import *

# open the specified input source
def openInput():
    if networkMode:
        return openNetwork()
    else:
        return openSerial()

# open the output files if they are specified
# set parsing to False if only an output file is specified
def openOutFiles():
    outFile = None
    invFile = None
    optFile = None
    jsonFile = None
    if outFileName != "":
        try:
            outFile = open(outFileName, writeMode)
            debug("debugFiles", "writing", outFileName)
        except:
            terminate(1, "Unable to open "+outFileName)
    if invFileName != "":
        try:
            invFile = open(invFileName, writeMode)
            if headers: writeHeaders(invFile, invItems, delim)
            debug("debugFiles", "writing", invFileName)
        except:
            terminate(1, "Unable to open "+invFileName)
    if optFileName != "":
        try:
            optFile = open(optFileName, writeMode)
            if headers: writeHeaders(optFile, optItems, delim)
            debug("debugFiles", "writing", optFileName)
        except:
            terminate(1, "Unable to open "+optFileName)
    if jsonFileName != "":
        try:
            jsonFile = open(jsonFileName, "w")
            jsonFile.close()
            debug("debugFiles", "writing", jsonFileName)
        except:
            terminate(1, "Unable to open "+jsonFileName)
    return (outFile, invFile, optFile, jsonFile)
    
# close all files        
def closeFiles(inFile, outFile, invFile, optFile, jsonFile):
    if inFile: inFile.close()
    if outFile: outFile.close()
    if invFile: invFile.close()
    if optFile: optFile.close()


