# SolarEdge configuration, logging, and debugging

import sys
import logging

# debug flags
debugFileName = "stderr"
haltOnDataParsingException = False

LOG_LEVEL_DATA = 9
LOG_LEVEL_RAW = 8

logging.addLevelName(LOG_LEVEL_DATA, 'DATA')
logging.addLevelName(LOG_LEVEL_RAW, 'RAW')

def _data_log(self, msg, *args, **kwargs):
    if self.isEnabledFor(LOG_LEVEL_DATA):
        self._log(LOG_LEVEL_DATA, msg, args, **kwargs)

def _raw_log(self, msg, *args, **kwargs):
    if self.isEnabledFor(LOG_LEVEL_RAW):
        self._log(LOG_LEVEL_RAW, msg, args, **kwargs)

logging.Logger.data = _data_log
logging.Logger.raw = _raw_log

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

