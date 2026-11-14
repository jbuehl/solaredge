# SPDX-License-Identifier: GPL-2.0-or-later
#
# Copyright (C) 2023 Olliver Schinagl <oliver@schinagl.nl>

"""
Wait for the system time to be valid.

semonitor provides the time to the inverter, and the time ends up in the
names and the data of its output, so it should never run with a bogus time.
A device without a battery backed clock has none until the time is
synchronized, which can take a while.

The time to wait for is set with the SE_START_EPOCH environment variable, as
a UNIX epoch or as an ISO 8601 date and time (without a time zone it is in
local time), for example '1735689600', '2025-01-01' or '2025-01-01T12:00Z'.
Without it the time this program was installed is used, as the time can not
be before that. SE_START_TIMEOUT is the number of seconds to wait for it, 60
when not set.
"""

import datetime as dt
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

START_EPOCH = "SE_START_EPOCH"
START_TIMEOUT = "SE_START_TIMEOUT"
DEFAULT_TIMEOUT = 60


class ClockError(Exception):
    """The time is not valid, or the settings to check it are not."""


def to_epoch(value):
    """
    Convert a UNIX epoch, or an ISO 8601 date and time, to a UNIX epoch.

    Raises:
        ClockError: If the value is neither of them.
    """
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return dt.datetime.fromisoformat(value).timestamp()
    except ValueError:
        msg = (
            f"Invalid '{START_EPOCH}' '{value}', expected a UNIX epoch or an"
            " ISO 8601 date and time."
        )
        raise ClockError(msg) from None


def default_epoch():
    """Return the time that has to have passed, when it is not set."""
    return Path(__file__).stat().st_mtime


def timeout(value):
    """
    Return the number of seconds to wait for the time, from its setting.

    Raises:
        ClockError: If the setting is not a number of seconds.
    """
    if not value:
        return DEFAULT_TIMEOUT
    try:
        return int(value)
    except ValueError:
        msg = (
            f"Invalid '{START_TIMEOUT}' '{value}', expected a number of"
            " seconds."
        )
        raise ClockError(msg) from None


def wait_for_valid_time(environ=None, now=None, sleep=None):
    """
    Wait, a little longer every time, until the time is not before the start.

    Args:
        environ: The environment with the settings, that of the process when
            not given.
        now: A function that returns the current UNIX epoch, time.time when
            not given.
        sleep: A function that waits for a number of seconds, time.sleep when
            not given.

    Raises:
        ClockError: If a setting is not valid, or the time is still before the
            start after the timeout.
    """
    environ = os.environ if environ is None else environ
    now = now or time.time
    sleep = sleep or time.sleep

    start = environ.get(START_EPOCH)
    start = to_epoch(start) if start else default_epoch()
    seconds = timeout(environ.get(START_TIMEOUT))

    interval = 1
    remaining = seconds
    while now() < start and remaining > 0:
        logger.warning(
            "System time %d older than %d, waiting (override with '%s') ...",
            now(),
            start,
            START_EPOCH,
        )
        sleep(interval)
        remaining -= interval
        interval += 1

    if now() < start:
        msg = f"System time still invalid after {seconds} seconds, giving up."
        raise ClockError(msg)
