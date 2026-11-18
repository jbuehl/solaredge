#!/usr/bin/env python3

import argparse
import contextlib
import datetime
import sys
import time
from pathlib import Path


# open the file to read from, which stays open until files is closed
def _open_input(args, files):
    if args.infile == "stdin":
        return sys.stdin
    try:
        return files.enter_context(Path(args.infile).open())
    except OSError:
        sys.stderr.write(f"We could not open {args.infile}. Exiting\n")
        sys.exit(1)


# the name of the file to write to, in a directory per day if asked for
def _output_path(args, curtime):
    curday = curtime.strftime("%Y-%m-%d")
    curhour = curtime.strftime("%Y-%m-%d-%H")
    curstore = curday if args.store_daily else curhour
    if args.make_daily_dir:
        Path(args.basedir, curday).mkdir(exist_ok=True)
        return (
            args.basedir + "/" + curday + "/" + args.prefix + curstore + ".json"
        )
    return args.basedir + "/" + args.prefix + curstore + ".json"


def main():
    # parse the command line arguments
    args = getargs()

    blank_max = 10  # Since we want to work on files and stdin. We will count the number of lines that are blank. If we process 10 blank lines and we are not doing stdin, we will assume that the file is done
    debug = args.debug
    openfilesecs = int(args.openfilesecs)
    # We always set looper = False for files, even if the args set it to true.
    looper = args.looper and args.infile == "stdin"
    with contextlib.ExitStack() as files:
        inFile = _open_input(args, files)

        lastwrite = 0
        # read the input forever or until we have 10 blank lines in the case of file as input
        writefilename = ""
        jsonStr = ""
        lcnt = 0
        filebuffersize = 0
        blank_cnt = 0
        while (
            looper or blank_cnt <= blank_max
        ):  # If stdin is set, the blank_cnt will be ignored
            lcnt += 1
            jsonStr = inFile.readline().strip()
            curepoch = int(time.time())
            # wait for and handle data coming in
            if jsonStr != "":
                blank_cnt = 0  # If we have data, reset the blank_cnt variable
                if debug:
                    sys.stderr.write(f"Got some data: {jsonStr}\n")
                tfname = _output_path(
                    args, datetime.datetime.now().astimezone()
                )
                if tfname != writefilename:
                    if debug:
                        sys.stderr.write(
                            "Looks like a new daily output file: "
                            f"Temp Name: {tfname} - Old Name: {writefilename}\n"
                        )
                    writefilename = tfname

                # The file is closed again right away, so we never keep it open
                with Path(writefilename).open(
                    "a", buffering=filebuffersize
                ) as writefile:
                    writefile.write(jsonStr + "\n")
                lastwrite = curepoch
                jsonStr = ""
            else:
                blank_cnt += 1
                time.sleep(0.5)
            # Let's not leave output files open if we haven't seen data in a while
            if curepoch - lastwrite > openfilesecs:
                if debug:
                    sys.stderr.write(
                        f"No data for {openfilesecs} seconds, closing file\n"
                    )
            # Keep track of when we are looping and report on it if debug is enabled.
            lreport = 60
            if lcnt % lreport == 0:
                lcnt = 0
                if debug:
                    curtime = datetime.datetime.now().astimezone()
                    curstr = curtime.strftime("%Y-%m-%d-%H:%m:%s")
                    sys.stderr.write(f"Looped {lreport} times at {curstr}\n")


def getargs():
    parser = argparse.ArgumentParser(
        description="Write the output of semonitor.py, unprocessed, to JSON files named after the day and hour in which each message was received.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-v",
        dest="debug",
        action="store_true",
        default=False,
        help="turn on very verbose debug messages",
    )
    parser.add_argument(
        "-b",
        dest="basedir",
        required=True,
        help="base directory to put the files into (required)",
    )
    parser.add_argument(
        "-p",
        dest="prefix",
        default="solardata_",
        help="prefix for all JSON filenames",
    )
    parser.add_argument(
        "-d",
        dest="store_daily",
        default=False,
        action="store_true",
        help="Store daily files (YYYY-MM-DD) instead of hourly files (YYYY-MM-DD-hh); results in larger files.",
    )
    parser.add_argument(
        "-t",
        dest="openfilesecs",
        default="120",
        help="Close the open output files after this many seconds without new data, and wait for more data.",
    )
    parser.add_argument(
        "-w",
        dest="looper",
        default=False,
        action="store_true",
        help="Wait forever for data on stdin, e.g. for a live semonitor.py; only applies when infile is stdin; without it, exit gracefully after 10 failed reads from stdin, so that piping in a file with cat returns.",
    )
    parser.add_argument(
        "-m",
        dest="make_daily_dir",
        default=False,
        action="store_true",
        help="Create a directory per day (YYYY-MM-DD) for the files; otherwise all files go into the base directory (-b).",
    )
    parser.add_argument(
        "infile",
        default="stdin",
        nargs="?",
        help="File to process, then exit; the default, stdin, reads piped data.",
    )

    defargs = parser.parse_args()
    if defargs.looper and defargs.infile != "stdin":
        sys.stderr.write(
            "Warning: wait forever (-w) only applies to stdin, "
            "not waiting for more data from the infile\n"
        )

    return defargs


if __name__ == "__main__":
    main()
