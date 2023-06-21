#!/usr/bin/env python3

## Tiny Syslog Server in Python.
##
## This is a tiny syslog server that is able to receive UDP based syslog
## entries on a specified port and save them to a file.
## That's it... it does nothing else...
## There are a few configuration parameters.
## Original sourced from the gist at https://gist.github.com/marcelom/4218010

LOG_DIR = 'logFiles'
LOG_FILE = '{}/syslog.log'.format(LOG_DIR)
HOST, PORT = "0.0.0.0", 514

#
# NO USER SERVICEABLE PARTS BELOW HERE...
#

import logging
import SocketServer
import os.path

if not os.path.isdir(LOG_DIR):
    os.mkdir(LOG_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    datefmt='',
    filename=LOG_FILE,
    filemode='a')


class SyslogUDPHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        data = bytes.decode(self.request[0].strip())
        socket = self.request[1]
        print("%s : " % self.client_address[0], str(data))
        logging.info(str(data))


if __name__ == "__main__":
    try:
        server = SocketServer.UDPServer((HOST, PORT), SyslogUDPHandler)
        server.serve_forever(poll_interval=0.5)
    except (IOError, SystemExit):
        raise
    except KeyboardInterrupt:
        print("Crtl+C Pressed. Shutting down.")
