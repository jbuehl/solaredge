#!/usr/bin/env python3

import argparse
import gzip
import json
import logging
import os
import queue
import select
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import influxdb
from dateutil import tz
from math import isnan

STDIN_TIMEOUT = 1
DB_ERROR_SLEEP = 30


@dataclass
class InfluxParams:
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


class DateError(Exception):
    pass


class EndOfFile(Exception):
    pass


class Se2Influx:
    def __init__(
        self,
        influx_params: InfluxParams,
        queue_size: int,
        log_path: Optional[str],
        max_log_size: int,
        local_tz: Optional[str],
        stat_timer_secs: Optional[int],
    ) -> None:

        self.influx_params = influx_params
        self.log_path = log_path
        self.max_log_size = max_log_size
        self.stat_timer_secs = stat_timer_secs

        self.local_tz = tz.gettz(local_tz) if local_tz is not None else tz.tzlocal()
        if self.local_tz is None:
            sys.exit(f"Time-zone not found: {local_tz}")

        self.writer_queue = queue.Queue(maxsize=queue_size)
        self.logger_queue = queue.Queue(maxsize=queue_size)
        self.shutdown = threading.Event()

    def run(self) -> None:
        """
        Run method;  start our read, write and (optionally) logger threads and then
        block forever or until one of the threads exits (which should only happen
        if they hit an exception)
        """

        logging.info("Starting reader & writer threads")
        reader_thread = threading.Thread(target=self.reader, daemon=True)
        reader_thread.setName("reader")
        writer_thread = threading.Thread(target=self.writer, daemon=True)
        writer_thread.setName("writer")
        threads = [reader_thread, writer_thread]

        if self.log_path:
            logging.info("Starting logger thread")
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
                    logging.warning("Thread for %s shut down", thread.name)
                    self.shutdown.set()

            time.sleep(1)

        for thread in threads:
            thread.join()

        logging.info("%s lines left in writer queue", self.writer_queue.qsize())
        logging.info("%s lines left in logger queue", self.logger_queue.qsize())

    def reader(self) -> None:
        """
        Reader method: execute a blocking read on stdin with a timeout, after which
        we check to see if we need to shutdown.  Any data gets sent to our output queues
        for ingestion by writer threads.
        """
        try:
            while True:
                while sys.stdin in select.select([sys.stdin], [], [], STDIN_TIMEOUT)[0]:
                    line = sys.stdin.readline()
                    if not line:
                        raise EndOfFile()
                    self.writer_queue.put(line)

                    if self.log_path:
                        self.logger_queue.put(line)

                if self.shutdown.is_set():
                    return

        except EndOfFile:
            logging.info("Reached end of input")
        except Exception as e:
            logging.error("Error reading from stdin: %s", e)

    def writer(self) -> None:
        """
        Writer method: read data from our queue, parse the json, turn it into
        valid influxdb data points, and then write it to our influxDB. Based on
        the configured retries, we may end up blocking forever on the write if
        the DB is down/unavailable.
        """

        logging.info("Connecting to InfluxDB")
        db_client = influxdb.InfluxDBClient(**self.influx_params.__dict__)

        # Create the database if it doesn't exist
        try:
            available_dbs = [db["name"] for db in db_client.get_list_database()]
            if self.influx_params.database not in available_dbs:
                logging.info(
                    "DB %s missing; attempting to create", self.influx_params.database
                )
                db_client.create_database(self.influx_params.database)
        except Exception as e:
            logging.error("Unable to connect to influxdb host or create DB: %s", e)
            return

        data_points_written = 0
        last_stat_print = int(time.time())
        while True:
            if self.stat_timer_secs is not None:
                now = int(time.time())
                if now > last_stat_print + self.stat_timer_secs:
                    logging.info("Data points written to DB: %s", data_points_written)
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
            except json.decoder.JSONDecodeError as e:
                logging.error("Got bad JSON data; %s -- %s", line, e)
                continue

            data_out = []
            try:
                for hw_type in ("inverters", "optimizers"):
                    for serial, hw_data in se_data[hw_type].items():
                        # InfluxDB does not like NaN floats, so we filter them out
                        hw_data = {
                            k: v
                            for k, v in hw_data.items()
                            if not (isinstance(v, float) and isnan(v))
                        }
                        utc_date = self._pop_utc_date(hw_data)
                        data_out.append(
                            {
                                "measurement": hw_type,
                                "tags": {"serial": serial},
                                "time": utc_date,
                                "fields": hw_data,
                            }
                        )

            except KeyError as e:
                logging.error(
                    "Decoded JSON missing required fields: %s -- %s", se_data, e
                )

            except DateError as e:
                logging.error("Error converting dates in JSON: %s -- %s", se_data, e)

            if not data_out:
                continue

            try:
                logging.debug("Writing to influxdb: %s", data_out)
                db_client.write_points(data_out)
                data_points_written += len(data_out)
            except Exception as e:
                logging.error("Error writing to influx db: %s", e)

    def logger(self) -> None:
        """
        Logger method:  this just takes our input data (read from stdin and
        written to our input queue) and writes it verbatim out to a file, with
        options for file rotation and compression.  This is useful if we need
        to later replay data and re-insert it into our influx DB (influxDB
        handles duplicate data points by overwriting field data, so this should
        be fine)
        """

        while True:
            try:
                log_fh = open(self.log_path, "a")
            except Exception as e:
                logging.error("Error opening %s: %s", self.log_path, e)
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
                except Exception as e:
                    logging.error("Error writing to %s: %s", self.log_path, e)
                    return

                size = os.stat(self.log_path).st_size
                if self.max_log_size and size > self.max_log_size:
                    log_fh.close()
                    try:
                        self._rotate_log()
                    except Exception as e:
                        logging.error("Failed to rotate file: %s, %s", self.log_path, e)
                    break

    def _rotate_log(self) -> None:
        """
        Rotate and copress logs once they get too big
        """

        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        log_root, sep, log_ext = self.log_path.rpartition(".")
        if not log_root:
            log_root = log_ext
            log_ext = ""

        gz_log = f"{log_root}-{ts}{sep}{log_ext}.gz"

        with open(self.log_path, "rb") as f_in:
            with gzip.open(gz_log, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        with open(self.log_path, "w"):
            pass

    def _pop_utc_date(self, data: Dict[str, Any]) -> str:
        """
        Take a semonitor data strict, remove the time and date fields, and then
        convert them (using a user-specified timezone, if existant, or otherwise
        our local machine timezone) to a UTC-based string format required by
        python-influxdb
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

    parser = argparse.ArgumentParser(
        description="Read semonitor.py output and write to an influxdb, and optionally a log file",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    db_args = parser.add_argument_group(description="InfluxDB options")
    db_args.add_argument(
        "--host", help="hostname to connect to InfluxDB", default="localhost"
    )
    db_args.add_argument("--port", help="port to connect to InfluxDB", default=8086)
    db_args.add_argument("--username", help="user to connect", default="root")
    db_args.add_argument("--password", help="password of the user", default="root")
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
        help="number of seconds to wait for your client to establish a connection",
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

    other_args = parser.add_argument_group(description="Control options")
    other_args.add_argument(
        "--queue_size", help="Size (in lines) to limit buffer queues to", default=10000
    )
    other_args.add_argument(
        "--log_path",
        help="Log file to semonitor.py data to; leave unset to prevent writing log data",
        type=str,
    )
    other_args.add_argument(
        "--max_log_size",
        help="Size in bytes after which to rotate+compress logged data",
        default=1024000,
    )
    other_args.add_argument(
        "--local_tz",
        help=(
            "Timezone string (from /usr/share/zoneinfo/) that our inverter is set to; "
            "if unset will default to local machine tz"
        ),
        type=str,
    )
    other_args.add_argument(
        "--stat_timer_secs",
        help="Print # data points written every N seconds; if unset print nothing",
        type=int,
    )
    other_args.add_argument(
        "--debug",
        action="store_true",
        help="Display debug-level log messages",
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
        args.log_path,
        args.max_log_size,
        args.local_tz,
        args.stat_timer_secs,
    )
    se2influx.run()
