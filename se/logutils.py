# SolarEdge logging and debugging

import sys
import logging
import traceback
import time

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

# log an incoming or outgoing data message
# call internal _log() method to ensure caller information is properly reported
def _message_log(self, direction, seq, msg, endPoint=""):
    if not self.isEnabledFor(logging.DEBUG):
        return
#    if direction == "-->":
#        self._log(logging.DEBUG, " ", ())
    self._log(logging.DEBUG, "%s %s message: %s length: %s", (endPoint, direction, seq, len(msg)))
    if self.isEnabledFor(LOG_LEVEL_RAW):
        for l in format_data(msg):
            self._log(LOG_LEVEL_RAW, l, ())
#    if direction == "<--":
#        self._log(logging.DEBUG, " ", ())

# hex dump data
def format_data(data):
    line_width = 16
    for i in range(0, len(data), line_width):
        yield "data:       " + ' '.join("{:02x}".format(x) for x in data[i:i+line_width])

logging.Logger.data = _data_log
logging.Logger.raw = _raw_log
logging.Logger.message = _message_log

# set a state variable
def setState(state, item, value):
    state[item] = [time.time(), value]

# dump out the state variables and stack traces of all threads
def dumpState(state):
    logger = logging.getLogger(__name__)
    logger.info("state:")
    for item in state.keys():
        logger.info("      "+time.strftime("%H:%M:%S", time.localtime(state[item][0]))+" "+item+": "+str(state[item][1]))
    for threadId, stack in sys._current_frames().items():
        logger.info("ThreadID: %s" % threadId)
        for filename, lineno, name, line in traceback.extract_stack(stack):
            logger.info('      File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                logger.info("            "+line)
