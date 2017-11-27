#!/usr/bin/env python

# Convert SolarEdge inverter performance monitoring data from JSON to CSV

import json
import argparse
import csv

from common import unwrap_metricsDict


if __name__ == "__main__":

    def deprecated(s):
        raise argparse.ArgumentTypeError("Deprecated option.")

    parser = argparse.ArgumentParser(description='reads a file containing JSON performance data and outputs a separate comma delimited file for each device type (eg inverter, optimizer, battery) encountered that is suitable for input to a spreadsheet.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-a", dest="append", action="store_true", default=False, help="append to inverter and optimizer files")
    parser.add_argument("-d", dest="delimeter", default=",", help="csv file delimiter")
    parser.add_argument("-t", dest="headers", action="store_true", default=False, help="write column headers to csv files")
    parser.add_argument("-p", dest="prefix", required=True, help="prefix for all csv filenames")
    parser.add_argument("-i", type=deprecated, help="The -i option is deprecated, use -p \"csvFileNamePrefix\" instead")
    parser.add_argument("-o", type=deprecated, help="The -o option is deprecated, use -p \"csvFileNamePrefix\" instead")
    parser.add_argument("-e", type=deprecated, help="The -e option is deprecated, use -p \"csvFileNamePrefix\" instead")
    parser.add_argument("infile", type=argparse.FileType('r'), default="-", nargs='?', help="File containing performance data in JSON format")

    args = parser.parse_args()

    devsFile = {}

    # process the data
    for jsonStr in args.infile:
        for baseName, devAttrs in unwrap_metricsDict(json.loads(jsonStr)):
            devName, devId = baseName.split(".", 1)
            if devName not in devsFile:
                devsFileName = '{}.{}.csv'.format(args.prefix, devName)
                itemNames = [ "__Identifier__"] + sorted(devAttrs.keys())
                devsFile[devName] = csv.DictWriter(open(devsFileName, "a" if args.append else "w"), itemNames)
                if args.headers:
                    devsFile[devName].writeheader()

            devAttrs["__Identifier__"] = devId
            # the default for DictWriter is to use repr() for floats so stringify everything before writing
            # https://docs.python.org/2/library/csv.html#csv.writer
            for k,v in devAttrs.iteritems():
                devAttrs[k] = str(v)
            devsFile[devName].writerow(devAttrs)
