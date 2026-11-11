#!/usr/bin/env python3

import time
import os
import sys
import datetime
from collections import OrderedDict
import argparse

def main():
    # parse the command line arguments
    args = getargs()

    blank_max = 10 # Since we want to work on files and stdin. We will count the number of lines that are blank. If we process 10 blank lines and we are not doing stdin, we will assume that the file is done
    basedir = args.basedir
    debug = args.debug
    prefix = args.prefix
    openfilesecs = int(args.openfilesecs)
    store_daily = args.store_daily
    make_daily_dir = args.make_daily_dir
    looper = args.looper
    if args.infile == "stdin":
        inFile = sys.stdin
    else:
        try:
            inFile = open(args.infile, "r")
        except:
            print("We could not open %s. Exiting" % ars.infile)
            sys.exit(1)
        # We always set looper = False for files, even if the args set it to true.
        looper = False

    lastwrite = 0
    # read the input forever or until we have 10 blank lines in the case of file as input
    writefile = None
    writefilename = ""
    jsonStr = ""
    lcnt = 0
    filebuffersize = 0
    blank_cnt = 0
    while looper or blank_cnt <= blank_max: # If stdin is set, the blank_cnt will be ignored
        lcnt += 1
        jsonStr = inFile.readline().strip()
        curepoch = int(time.time())
        # wait for and handle data coming in
        if jsonStr != "":
            blank_cnt = 0 # If we have data, reset the blank_cnt variable
            if debug:
                print("Got some data: %s" % jsonStr)
            curtime = datetime.datetime.now()
            curday = curtime.strftime("%Y-%m-%d")
            curhour = curtime.strftime("%Y-%m-%d-%H")
            if store_daily == True:
                curstore = curday
            else:
                curstore = curhour
            if make_daily_dir == True:
                if not os.path.isdir(basedir + "/" + curday):
                    os.mkdir(basedir + "/" + curday)
                tfname = basedir + "/" + curday + "/" + prefix + curstore + ".json"
            else:
                tfname = basedir + "/" + prefix + curstore + ".json"
            if tfname != writefilename:
                if debug:
                    print("Looks like a new daily output file: Temp Name: %s - Old Name: %s" % (tfname, writefilename))
                if writefile is not None:
                    writefile.close()
                    writefile = None
                writefilename = tfname

            if writefile is None:
                writefile  = open(writefilename, "a",  buffering=filebuffersize)
            writefile.write(jsonStr + "\n")
            lastwrite = curepoch
            writefile.close()
            writefile = None
            jsonStr = ""
        else:
            blank_cnt += 1
            time.sleep(0.5)
        # Let's not leave output files open if we haven't seen data in a while
        if curepoch - lastwrite > openfilesecs:
            if debug:
                print("No data for %s seconds, closing file" % openfilesecs)
            if writefile is not None:
                writefile.close()
                writefile = None
        # Keep track of when we are looping and report on it if debug is enabled.
        lreport = 60
        if lcnt % lreport == 0:
            lcnt = 0
            if debug:
                curtime = datetime.datetime.now()
                curstr = curtime.strftime("%Y-%m-%d-%H:%m:%s")
                print("Looped %s times at %s" % (lreport, curstr))



def getargs():
    parser = argparse.ArgumentParser(description='Write the output of semonitor.py, unprocessed, to JSON files named after the day and hour in which each message was received.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-v", dest="debug", action="store_true",  default=False, help="turn on very verbose debug messages")
    parser.add_argument("-b", dest="basedir", required=True, help="base directory to put the files into (required)")
    parser.add_argument("-p", dest="prefix", default="solardata_", help="prefix for all JSON filenames")
    parser.add_argument("-d", dest="store_daily", default=False, action="store_true", help="Store daily files (YYYY-MM-DD) instead of hourly files (YYYY-MM-DD-hh); results in larger files.")
    parser.add_argument("-t", dest="openfilesecs", default="120", help="Close the open output files after this many seconds without new data, and wait for more data.")
    parser.add_argument("-w", dest="looper", default=False, action="store_true", help="Wait forever for data on stdin, e.g. for a live semonitor.py; only applies when infile is stdin; without it, exit gracefully after 10 failed reads from stdin, so that piping in a file with cat returns.")
    parser.add_argument("-m", dest="make_daily_dir", default=False, action="store_true", help="Create a directory per day (YYYY-MM-DD) for the files; otherwise all files go into the base directory (-b).")
    parser.add_argument("infile", default="stdin", nargs='?', help="File to process, then exit; the default, stdin, reads piped data.")

    defargs = parser.parse_args()
    if defargs.looper == True and defargs.infile != "stdin":
        print("Warning: wait forever (-w) only applies to stdin, not waiting for more data from the infile")

    return defargs






if __name__ == "__main__":
    main()
