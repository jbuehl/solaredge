"""Convert SolarEdge inverter performance monitoring data from JSON to CSV."""

import argparse
import contextlib
import csv
import json
from pathlib import Path

from se.metrics import unwrap_metrics_dict


def deprecated(_s):
    """Reject a deprecated command line option with an error."""
    msg = "Deprecated option."
    raise argparse.ArgumentTypeError(msg)


def main(argv=None):
    """
    Write a CSV file per device type from the JSON performance data read.

    Args:
        argv: The command line arguments to use, or None for those of the process.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Read a file containing JSON performance data and output a "
            "separate comma-delimited file for each device type (e.g. "
            "inverter, optimizer, battery) encountered that is suitable for "
            "input to a spreadsheet."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-a",
        dest="append",
        action="store_true",
        default=False,
        help="append to inverter and optimizer files",
    )
    parser.add_argument(
        "-d", dest="delimiter", default=",", help="CSV file delimiter"
    )
    parser.add_argument(
        "-t",
        dest="headers",
        action="store_true",
        default=False,
        help="write column headers to CSV files",
    )
    parser.add_argument(
        "-p", dest="prefix", required=True, help="prefix for all CSV filenames"
    )
    parser.add_argument(
        "-i",
        type=deprecated,
        help='The -i option is deprecated, use -p "csvFileNamePrefix" instead.',
    )
    parser.add_argument(
        "-o",
        type=deprecated,
        help='The -o option is deprecated, use -p "csvFileNamePrefix" instead.',
    )
    parser.add_argument(
        "-e",
        type=deprecated,
        help='The -e option is deprecated, use -p "csvFileNamePrefix" instead.',
    )
    parser.add_argument(
        "infile",
        type=argparse.FileType("r"),
        default="-",
        nargs="?",
        help="file containing performance data in JSON format",
    )

    args = parser.parse_args(argv)

    devs_file = {}

    # process the data, and close the CSV files when we are done
    with contextlib.ExitStack() as csv_files:
        for json_str in args.infile:
            for base_name, dev_attrs in sorted(
                unwrap_metrics_dict(json.loads(json_str))
            ):
                dev_name, dev_id = base_name.split(".", 1)
                if dev_name not in devs_file:
                    devs_file_name = f"{args.prefix}.{dev_name}.csv"
                    item_names = ["__Identifier__", *sorted(dev_attrs.keys())]
                    devs_file[dev_name] = csv.DictWriter(
                        csv_files.enter_context(
                            Path(devs_file_name).open(
                                "a" if args.append else "w"
                            )
                        ),
                        item_names,
                    )
                    if args.headers:
                        devs_file[dev_name].writeheader()

                dev_attrs["__Identifier__"] = dev_id
                devs_file[dev_name].writerow(dev_attrs)


if __name__ == "__main__":
    main()
