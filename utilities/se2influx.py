#!/usr/bin/env python3
"""Read semonitor.py output and write it to an InfluxDB and a log file."""

import argparse
import contextlib
import gzip
import json
import logging
import queue
import select
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from math import isnan
from pathlib import Path
from typing import Any

import influxdb
from dateutil import tz

STDIN_TIMEOUT = 1
DB_ERROR_SLEEP = 30

logger = logging.getLogger(__name__)


@dataclass
class InfluxParams:
    """Connection settings for the InfluxDB server."""

    host: str
    port: int
    username: str
    password: str
    database: str
    ssl: bool
    verify_ssl: bool
    timeout: int
    retries: int
    use_udp: bool
    udp_port: int


@dataclass
class LogParams:
    """Settings for the optional log file of raw semonitor output."""

    path: str | None
    max_size: int


class DateError(Exception):
    """Raised when the date and time of a semonitor message cannot be converted."""


class Se2Influx:
    """Read semonitor data from stdin and write it to InfluxDB and a log file."""

    def __init__(
        self,
        influx_params: InfluxParams,
        queue_size: int,
        log_params: LogParams,
        local_tz: str | None,
        stat_timer_secs: int | None,
    ) -> None:
        """
        Store the settings and create the queues and the shutdown event.

        Args:
            influx_params: The InfluxDB connection settings.
            queue_size: The maximum number of lines in each queue.
            log_params: The settings for the optional log file.
            local_tz: The name of the time zone the inverter uses, or None
                for the local machine time zone.
            stat_timer_secs: How often, in seconds, to log the number of data
                points written, or None to log nothing.
        """
        self.influx_params = influx_params
        self.log_path = log_params.path
        self.max_log_size = log_params.max_size
        self.stat_timer_secs = stat_timer_secs

        self.local_tz = (
            tz.gettz(local_tz) if local_tz is not None else tz.tzlocal()
        )
        if self.local_tz is None:
            sys.exit(f"Time-zone not found: {local_tz}")

        self.writer_queue = queue.Queue(maxsize=queue_size)
        self.logger_queue = queue.Queue(maxsize=queue_size)
        self.shutdown = threading.Event()

    def run(self) -> None:
        """
        Start the reader, writer and (optionally) logger threads.

        Then block until one of the threads exits, which should only happen if
        it hits an exception.
        """
        logger.info("Starting reader & writer threads")
        reader_thread = threading.Thread(target=self.reader, daemon=True)
        reader_thread.setName("reader")
        writer_thread = threading.Thread(target=self.writer, daemon=True)
        writer_thread.setName("writer")
        threads = [reader_thread, writer_thread]

        if self.log_path:
            logger.info("Starting logger thread")
            logger_thread = threading.Thread(target=self.logger, daemon=True)
            logger_thread.setName("logger")
            threads.append(logger_thread)

        for thread in threads:
            thread.start()

        while True:
            if self.shutdown.is_set():
                break
            for thread in threads:
                if not thread.is_alive():
                    logger.warning("Thread for %s shut down", thread.name)
                    self.shutdown.set()

            time.sleep(1)

        for thread in threads:
            thread.join()

        logger.info("%s lines left in writer queue", self.writer_queue.qsize())
        logger.info("%s lines left in logger queue", self.logger_queue.qsize())

    def reader(self) -> None:
        """
        Read lines from stdin and pass them to the output queues.

        Each read blocks with a timeout, after which we check to see if we need
        to shut down. Any data gets sent to our output queues for ingestion by
        writer threads.
        """
        try:
            while True:
                while (
                    sys.stdin
                    in select.select([sys.stdin], [], [], STDIN_TIMEOUT)[0]
                ):
                    line = sys.stdin.readline()
                    if not line:
                        logger.info("Reached end of input")
                        return
                    self.writer_queue.put(line)

                    if self.log_path:
                        self.logger_queue.put(line)

                if self.shutdown.is_set():
                    return

        except Exception:
            logger.exception("Error reading from stdin")

    def writer(self) -> None:
        """
        Write data from our queue to InfluxDB.

        Reads the JSON from the queue, turns it into valid InfluxDB data points
        and writes them to our InfluxDB. Based on the configured retries, we may
        end up blocking forever on the write if the DB is down or unavailable.
        """
        logger.info("Connecting to InfluxDB")
        db_client = influxdb.InfluxDBClient(**self.influx_params.__dict__)

        if not self._create_database(db_client):
            return

        data_points_written = 0
        last_stat_print = int(time.time())
        while True:
            if self.stat_timer_secs is not None:
                now = int(time.time())
                if now > last_stat_print + self.stat_timer_secs:
                    logger.info(
                        "Data points written to DB: %s", data_points_written
                    )
                    data_points_written = 0
                    last_stat_print = now

            try:
                line = self.writer_queue.get(timeout=1)
            except queue.Empty:
                if self.shutdown.is_set():
                    return
                continue

            try:
                se_data = json.loads(line)
            except json.decoder.JSONDecodeError:
                logger.exception("Got bad JSON data; %s", line)
                continue

            data_out = self._data_points(se_data)
            if not data_out:
                continue

            try:
                logger.debug("Writing to influxdb: %s", data_out)
                db_client.write_points(data_out)
                data_points_written += len(data_out)
            except Exception:
                logger.exception("Error writing to influx db")

    def _create_database(self, db_client) -> bool:
        """Create the database if it doesn't exist, and return if it is there."""
        try:
            available_dbs = [db["name"] for db in db_client.get_list_database()]
            if self.influx_params.database not in available_dbs:
                logger.info(
                    "DB %s missing; attempting to create",
                    self.influx_params.database,
                )
                db_client.create_database(self.influx_params.database)
        except Exception:
            logger.exception("Unable to connect to influxdb host or create DB")
            return False
        return True

    def _data_points(self, se_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Turn the decoded JSON of a message into InfluxDB data points."""
        data_out = []
        try:
            for hw_type in ("inverters", "optimizers"):
                for serial, hw_data in se_data[hw_type].items():
                    # InfluxDB does not like NaN floats, so we filter them out
                    fields = {
                        k: v
                        for k, v in hw_data.items()
                        if not (isinstance(v, float) and isnan(v))
                    }
                    utc_date = self.pop_utc_date(fields)
                    data_out.append(
                        {
                            "measurement": hw_type,
                            "tags": {"serial": serial},
                            "time": utc_date,
                            "fields": fields,
                        }
                    )

        except KeyError:
            logger.exception(
                "Decoded JSON missing required fields: %s", se_data
            )

        except DateError:
            logger.exception("Error converting dates in JSON: %s", se_data)
        return data_out

    def logger(self) -> None:
        """
        Write the raw input data verbatim to the log file.

        This takes our input data (read from stdin and written to our input
        queue) and writes it out to a file, with options for file rotation and
        compression. This is useful if we need to later replay data and
        re-insert it into our InfluxDB (InfluxDB handles duplicate data points
        by overwriting field data, so this should be fine).
        """
        while True:
            with contextlib.ExitStack() as stack:
                try:
                    log_fh = stack.enter_context(Path(self.log_path).open("a"))
                except Exception:
                    logger.exception("Error opening %s", self.log_path)
                    return

                while True:
                    try:
                        line = self.logger_queue.get(timeout=1)
                    except queue.Empty:
                        if self.shutdown.is_set():
                            return
                        continue

                    try:
                        log_fh.write(line)
                        log_fh.flush()
                    except Exception:
                        logger.exception("Error writing to %s", self.log_path)
                        return

                    size = Path(self.log_path).stat().st_size
                    if self.max_log_size and size > self.max_log_size:
                        log_fh.close()
                        try:
                            self.rotate_log()
                        except Exception:
                            logger.exception(
                                "Failed to rotate file: %s", self.log_path
                            )
                        break

    def rotate_log(self) -> None:
        """Rotate and compress logs once they get too big."""
        ts = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
        log_root, sep, log_ext = self.log_path.rpartition(".")
        if not log_root:
            log_root = log_ext
            log_ext = ""

        gz_log = f"{log_root}-{ts}{sep}{log_ext}.gz"

        with (
            Path(self.log_path).open("rb") as f_in,
            gzip.open(gz_log, "wb") as f_out,
        ):
            shutil.copyfileobj(f_in, f_out)

        with Path(self.log_path).open("w"):
            pass

    def pop_utc_date(self, data: dict[str, Any]) -> str:
        """
        Remove the date and time fields and return them as a UTC string.

        The date and time are removed from data and converted (using the
        user-specified time zone, or otherwise our local machine time zone) to
        the UTC-based string format required by python-influxdb.
        """
        date = data.pop("Date")
        time = data.pop("Time")

        try:
            local_time = datetime.strptime(
                f"{date} {time}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=self.local_tz)
            utc_time = local_time.astimezone(tz.tzutc())
            return utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            raise DateError(e) from e


def parse_args() -> argparse.Namespace:
    """Parse and return the command line arguments."""
    parser = argparse.ArgumentParser(
        description="Read semonitor.py output and write to an InfluxDB, and optionally a log file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    db_args = parser.add_argument_group(description="InfluxDB options.")
    db_args.add_argument(
        "--host", help="hostname to connect to InfluxDB", default="localhost"
    )
    db_args.add_argument(
        "--port", help="port to connect to InfluxDB", default=8086
    )
    db_args.add_argument(
        "--username", help="username to connect as", default="root"
    )
    db_args.add_argument(
        "--password", help="password of the user", default="root"
    )
    db_args.add_argument(
        "--database", help="database name to connect to", default="semonitor"
    )
    db_args.add_argument(
        "--ssl",
        help="use https instead of http to connect to InfluxDB",
        action="store_true",
    )
    db_args.add_argument(
        "--verify_ssl",
        help="verify SSL certificates for HTTPS requests",
        action="store_true",
    )
    db_args.add_argument(
        "--timeout",
        help="Number of seconds to wait for your client to establish a connection.",
        type=int,
    )
    db_args.add_argument(
        "--retries",
        help="number of attempts your client will make before aborting",
        default=3,
    )
    db_args.add_argument(
        "--use_udp", help="use UDP to connect to InfluxDB", action="store_true"
    )
    db_args.add_argument(
        "--udp_port", help="UDP port to connect to InfluxDB", default=4444
    )

    other_args = parser.add_argument_group(description="Control options.")
    other_args.add_argument(
        "--queue_size",
        help="size (in lines) to limit buffer queues to",
        default=10000,
    )
    other_args.add_argument(
        "--log_path",
        help="Log file to write semonitor.py data to; leave unset to prevent writing log data.",
        type=str,
    )
    other_args.add_argument(
        "--max_log_size",
        help="size in bytes after which to rotate and compress logged data",
        default=1024000,
    )
    other_args.add_argument(
        "--local_tz",
        help=(
            "Timezone string (from /usr/share/zoneinfo/) that our inverter is set to; "
            "if unset, defaults to the local machine time zone."
        ),
        type=str,
    )
    other_args.add_argument(
        "--stat_timer_secs",
        help="Print # data points written every N seconds; if unset print nothing.",
        type=int,
    )
    other_args.add_argument(
        "--debug",
        action="store_true",
        help="display debug-level log messages",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    db_params = InfluxParams(
        args.host,
        args.port,
        args.username,
        args.password,
        args.database,
        args.ssl,
        args.verify_ssl,
        args.timeout,
        args.retries,
        args.use_udp,
        args.udp_port,
    )

    se2influx = Se2Influx(
        db_params,
        args.queue_size,
        LogParams(args.log_path, args.max_log_size),
        args.local_tz,
        args.stat_timer_secs,
    )
    se2influx.run()
