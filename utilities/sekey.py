#!/usr/bin/env python3

# Get the encryption key for an inverter

import json
import getopt
import sys
import struct
import binascii

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "o:")
try:
    inFile = open(args[0])
except:
    inFile = sys.stdin
outFile = sys.stdout
for opt in opts:
    if opt[0] == "-o":
        outFile = open(opt[1], "w")

# read 4 lines from the input
key = b''
for i in range(4):
    data = json.loads(inFile.readline().rstrip("\n"))
    print(data["data"]["value"])
    key += struct.pack("<L", data["data"]["value"])
outFile.write(binascii.hexlify(key).decode("ascii"))
