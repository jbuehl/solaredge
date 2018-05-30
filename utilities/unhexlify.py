#!/usr/bin/env python2

"""
used for decoding streams of hex such as those outputted by tshark

the encoding of stream data from tshark is normally necessary to distinguish which side of the conversation
a given messages is going to/from.  However, since the solaredge protocol is based on an RS485 (bus) protocol
all information about the source and destination addresses are encapsulated in the higher-level solaredge
protocol.
"""

import binascii
import sys

for l in sys.stdin:
    sys.stdout.write(binascii.unhexlify(l.strip()))
