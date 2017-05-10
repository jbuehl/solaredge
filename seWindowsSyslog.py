"""
A very basic alternative to the (linux world's) syslog module, so I can test semonitor
or a Windows machine without too much heartache.

Note that to see anything from this logger, a syslog server must be running, to capture and use the UDP packets sent
by the SysLogHandler.

For testing purposes on Windows, just start the Tiny Python Syslog server in another window before running semonitor.
"""

import logging
import logging.handlers
import os

class TimedRotatingFileHandlerUmasked(logging.handlers.TimedRotatingFileHandler):
    """
    A modification of the logging.handlers.TimedRotatingFileHandler

    It uses os.umask to give the owner and group read and write permissions to the log files.
    _open (in the parent classes) is the hidden method which actually opens and creates new log files.
    umask is a system level mask which contains the *bitwise negation* of the files permission mask.
    eg (octal) 002 umask results in (octal) permission 775 - or rather (775 & the linux default), where the linux
    default for a file is 666, so the result is 775 & 666 = 664.

    See
    http://stackoverflow.com/questions/1407474/does-python-logging-handlers-rotatingfilehandler-allow-creation-of-a-group-writa
    """
    def _open(self):
        prevUmask = os.umask(0o002)
        try:
            rtv = super(TimedRotatingFileHandlerUmasked, self)._open()
            os.umask(prevUmask)
            return rtv
        except:
            os.umask(prevUmask)
            raise


my_logger = logging.getLogger('syslog')
my_logger.setLevel(logging.DEBUG)

handler = logging.handlers.SysLogHandler()

# An alternative could be to make a handler that writes to a file, making a new file at midnight and keeping 3 backups
# handler = TimedRotatingFileHandlerUmasked("logFiles/{}.rotating.log".format(logFileName), when="midnight",
#             backupCount=3)

# Format each log message like this
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
# Attach the formatter to the handler
handler.setFormatter(formatter)
# Attach the handler to the logger
my_logger.addHandler(handler)

# And now pretend it *is* the syslog
syslog = my_logger.info

if __name__ == "__main__":

    my_logger.debug('this is debug')
    my_logger.critical('this is critical')
    syslog("This is an emulated syslog message")
