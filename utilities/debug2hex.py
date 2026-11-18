#!/usr/bin/env python3
"""
Convert a debug log back into a binary data file.

The log must have been created by semonitor.py with the -vvvv option which
dumps the raw data.

Usage:
  python debug2hex.py logFile [dataFile]
      logFile     file containing semonitor.py debug output created with the -vvvv option
      dataFile    file to write data to (default: stdout)
"""

import binascii
import contextlib
import sys
from pathlib import Path

with contextlib.ExitStack() as files:
    logFile = files.enter_context(Path(sys.argv[1]).open())
    try:
        dataFile = files.enter_context(Path(sys.argv[2]).open("wb"))
    except IndexError:
        dataFile = sys.stdout.buffer

    for line in logFile:
        if line[0:5] == "data:":
            dataFile.write(
                binascii.unhexlify(line[5:].replace(" ", "").strip())
            )
