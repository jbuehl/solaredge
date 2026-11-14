import os
import time
from pathlib import Path

import pytest

import se.clock
from se.clock import ClockError

START = 1_000_000


class Clock:
    # A clock that only moves when the code sleeps.
    def __init__(self, now):
        self.now = now
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def wait(clock, **environ):
    se.clock.wait_for_valid_time(environ, now=clock.time, sleep=clock.sleep)


# --- the time to wait for ----------------------------------------------------


def test_an_epoch_is_taken_as_it_is():
    assert se.clock.to_epoch("1735689600") == 1735689600


def test_a_date_and_time_with_a_time_zone_is_that_time():
    assert se.clock.to_epoch("2025-01-01T01:00:00+01:00") == 1735689600
    assert se.clock.to_epoch("2025-01-01T00:00:00Z") == 1735689600


def test_a_date_and_time_without_a_time_zone_is_in_local_time():
    expected = time.mktime((2025, 1, 1, 12, 30, 0, 0, 0, -1))

    assert se.clock.to_epoch("2025-01-01T12:30") == expected
    assert se.clock.to_epoch("2025-01-01") == time.mktime(
        (2025, 1, 1, 0, 0, 0, 0, 0, -1)
    )


@pytest.mark.parametrize("value", ["nonsense", "yesterday", "12:00", "1.5x"])
def test_anything_else_is_an_error(value):
    with pytest.raises(ClockError, match="'SE_START_EPOCH' '" + value):
        se.clock.to_epoch(value)


def test_the_default_is_the_time_of_the_program():
    assert se.clock.default_epoch() == Path(se.clock.__file__).stat().st_mtime


# --- waiting -----------------------------------------------------------------


def test_nothing_is_waited_for_when_the_time_is_valid():
    clock = Clock(START)

    wait(clock, SE_START_EPOCH=str(START))

    assert clock.sleeps == []


def test_the_time_is_waited_for_a_little_longer_every_time():
    clock = Clock(START - 5)

    wait(clock, SE_START_EPOCH=str(START))

    assert clock.sleeps == [1, 2, 3]


def test_the_wait_ends_with_an_error_after_the_timeout():
    clock = Clock(START - 1000)

    with pytest.raises(ClockError, match="still invalid after 3 seconds"):
        wait(clock, SE_START_EPOCH=str(START), SE_START_TIMEOUT="3")

    assert clock.sleeps == [1, 2]


def test_the_timeout_defaults_to_a_minute():
    clock = Clock(START - 1000)

    with pytest.raises(ClockError, match="after 60 seconds"):
        wait(clock, SE_START_EPOCH=str(START))

    assert 60 <= sum(clock.sleeps) < 60 + len(clock.sleeps)


def test_a_timeout_of_zero_does_not_wait_at_all():
    clock = Clock(START - 1)

    with pytest.raises(ClockError):
        wait(clock, SE_START_EPOCH=str(START), SE_START_TIMEOUT="0")

    assert clock.sleeps == []


def test_the_timeout_has_to_be_a_number():
    with pytest.raises(ClockError, match="'SE_START_TIMEOUT' 'soon'"):
        wait(Clock(START), SE_START_EPOCH=str(START), SE_START_TIMEOUT="soon")


def test_an_invalid_start_is_an_error_even_when_the_time_is_valid():
    with pytest.raises(ClockError, match="'SE_START_EPOCH' 'nonsense'"):
        wait(Clock(START), SE_START_EPOCH="nonsense")


def test_an_empty_start_is_not_set():
    now = se.clock.default_epoch() + 1

    wait(Clock(now), SE_START_EPOCH="")


def test_without_a_start_the_time_has_to_be_after_the_program_was_installed():
    installed = se.clock.default_epoch()

    wait(Clock(installed + 1))
    with pytest.raises(ClockError):
        wait(Clock(installed - 1), SE_START_TIMEOUT="0")


def test_the_environment_of_the_process_is_used_by_default(monkeypatch):
    monkeypatch.setattr(os, "environ", {"SE_START_EPOCH": "nonsense"})

    with pytest.raises(ClockError, match="'SE_START_EPOCH' 'nonsense'"):
        se.clock.wait_for_valid_time()


def test_the_wait_is_reported(caplog):
    caplog.set_level("WARNING", logger="se.clock")

    wait(Clock(START - 1), SE_START_EPOCH=str(START))

    assert caplog.messages == [
        (
            f"System time {START - 1} older than {START}, waiting"
            " (override with 'SE_START_EPOCH') ..."
        )
    ]
