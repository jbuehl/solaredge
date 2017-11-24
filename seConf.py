# SolarEdge configuration, logging, and debugging

import sys
import logging

# debug flags
debugFileName = "stderr"
haltOnDataParsingException = False

LOG_LEVEL_MSG = 9
LOG_LEVEL_RAW = 8

logging.addLevelName(LOG_LEVEL_MSG, 'MESSAGE')
logging.addLevelName(LOG_LEVEL_RAW, 'RAW')

logging.Logger.message = lambda self, message, *args, **kws: self.log(LOG_LEVEL_MSG, message, *args, **kws) 
logging.Logger.raw = lambda self, message, *args, **kws: self.log(LOG_LEVEL_RAW, message, *args, **kws) 

logger = logging.getLogger(__name__)

# log an incoming or outgoing data message
def logMsg(direction, seq, msg, endPoint=""):
    if direction == "-->":
        logger.debug(" ")
    logger.debug("%s %s message: %s length: %s", endPoint, direction, seq, len(msg))
    for l in format_data(msg):
        logger.raw(l)
    if direction == "<--":
        logger.debug(" ")

# hex dump data
def format_data(data):
    line_width = 16
    for i in range(0, len(data), line_width):
        yield "data:       " + ' '.join(x.encode('hex') for x in data[i:i+line_width])

