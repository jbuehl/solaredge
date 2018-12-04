#!/usr/bin/env python

import time
import sys
import datetime
from collections import OrderedDict
import argparse

def main():
# state values
    args = getargs()

    blank_max = 10 # Since we want to work on files and std in. We will count the number of lines that are blank. If we process 100 blank lines and we are not doing stdin, we will assume that the file is done
    basedir = args.basedir
    debug = args.debug
    prefix = args.prefix
    openfilesecs = int(args.openfilesecs)
    store_daily = args.store_daily
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
# read the input forever or until we have 100 blank lines in the case of file as input
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
            tfname = basedir + "/" + prefix + curstore + ".json"
            if tfname != writefilename:
                if debug:
                    print("Looks like a new day: Temp Name: %s - Old Name: %s" % (tfname, writefilename))
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
                print("Well it's been %s seconds, closing file" % openfilesecs)
            if writefile is not None:
                writefile.close()
                writefile = None
        # Keep track of when we are looping and report on it of debug is enabled.
        lreport = 60
        if lcnt % lreport == 0:
            lcnt = 0
            if debug:
                curtime = datetime.datetime.now()
                curstr = curtime.strftime("%Y-%m-%d-%H:%m:%s")
                print("We've looped %s times at %s" % (lreport, curstr))



def getargs():
    parser = argparse.ArgumentParser(description='Takes output from semonitor.py and puts all output into json files based on the day and hour that the message was recieve. No processing is done, messages in from semonitor.py direct to files.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-D", dest="debug", action="store_true",  default=False, help="Turn on debug messages (verbose!)")
    parser.add_argument("-b", dest="basedir", required=True, help="This is the base directory to put files into (Required)")
    parser.add_argument("-p", dest="prefix", default="solardata_", help="prefix for all csv filenames (defaults to 'solardata_')")
    parser.add_argument("-d", dest="store_daily", default=False, action="store_true", help="Instead of using Hourly files (YYYY-MM-DD-hh) store in daily files (YYYY-MM-DD) - Results in larger files. Default is False (Use Hourly)")
    parser.add_argument("-t", dest="openfilesecs", default="120", help="If no data added to open outputfiles in this many seconds, then close them and wait for more data. Defaults to 120 seconds")
    parser.add_argument("-s", dest="infile", default="stdin", help="File to process. The Default of stdin is used to pipe data to this script. Otherwise it will just process a single file (provided by -s) and exit)")
    parser.add_argument("-w", dest="looper", default=False, action="store_true", help="Wait forever on stdin. This only applies when -s is not set or set to stdin. It will wait forever on listening to stdin. Use this to wait for long running processes. If this is not set, after 10 attempts to read from stdin, it will exit gracefully. This is the default so you can cat files to this, and have it return. If you are running this as part of a semonitor.py process that is live, then set -w so it can go a long time without input and not close")

    defargs = parser.parse_args()
    if defargs.looper == True and defargs.infile != "stdin": 
        print("Warning: You have set wait forever (-w) on a infile that is not stdin, we will NOT wait forever")

    return defargs



 


if __name__ == "__main__":
    main()

