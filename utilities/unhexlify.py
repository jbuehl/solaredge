#!/usr/bin/env python2

"""
used for decoding streams of hex such as those outputted by tshark
"""

import binascii
import sys

for l in sys.stdin:
    sys.stdout.write(binascii.unhexlify(l.strip()))
