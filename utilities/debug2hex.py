# Utility to convert a debug log back into a binary data file.
# The log must have been created by semonitor.py with the -vvvv option which
# dumps the raw data.

# Usage:
#   python debug2hex.py logFile [dataFile]
#       logFile     file containing semonitor.py debug output created with the -vvvv option
#       dataFile    file to write data to (default: stdout)

import binascii
import sys

logFile = open(sys.argv[1])
try:
    datafile = open(sys.argv[2], "wb")
except IndexError:
    dataFile = sys.stdout

for line in logFile:
    if line[0:5] == "data:":
         dataFile.write(binascii.unhexlify(line[5:].replace(" ", "").strip()))
