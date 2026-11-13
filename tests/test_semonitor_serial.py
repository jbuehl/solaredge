import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import time

import pytest

import se.msg

from .conftest import REPO_ROOT, SEMONITOR

fcntl = pytest.importorskip("fcntl")
termios = pytest.importorskip("termios")
tty = pytest.importorskip("tty")

# The bytes travel over a pseudo terminal to the real pyserial, which opens
# and reads the port as it does a real one, so this tests the whole way from
# the bytes on the line to the JSON. A pseudo terminal has no UART: parity,
# framing and baud rate errors do not exist, they show up as wrong bytes,
# which the faults below inject. The line is driven, not slowed down, and
# nothing depends on timing.

SAMPLE = "Geoff99.190801.1135.test"
MAGIC = b"\x12\x34\x56\x79"
DEADLINE = 20  # seconds, only used up when something is wrong
EXIT_WAIT = 10  # seconds, to see that semonitor does not end

# The frames of the recording (what follows each magic number) that hold
# measurements, and the line of the golden JSON that each one becomes.
JSON_FRAMES = {5: 0, 7: 1, 9: 2, 15: 3, 18: 4, 20: 5}
FIRST = min(JSON_FRAMES)
LAST = max(JSON_FRAMES)
TARGET = 9  # the frame that the faults are injected in

LENGTH_ERRORS = (
    "Data length is too big for the message",
    "Data length doesn't match inverse length",
)
CHECKSUM_ERRORS = ("Checksum error",)
EXTRA_BYTES = ("extra bytes",)
TRUNCATED = ("too short", "Data length is too big for the message")
ANY_ERROR = (*LENGTH_ERRORS, *CHECKSUM_ERRORS, "too short", "Failed to parse")

# Pyserial only lists the real ports, so the pseudo terminal is added to the
# list. The test is told that the port is open, as pyserial throws away what
# arrived before.
LAUNCHER = """
import os, runpy, sys
import serial
import serial.tools.list_ports

ready_fd, port, script, *argv = sys.argv[1:]
sys.argv[:] = [script, *argv]
serial.tools.list_ports.comports = lambda: [(port, "pty", "n/a")]


class ReportingSerial(serial.Serial):
    def open(self):
        super().open()
        os.write(int(ready_fd), b"1")


serial.Serial = ReportingSerial
runpy.run_path(script, run_name="__main__")
"""


class SerialSemonitor:
    """semonitor.py, in a process of its own, on a pseudo terminal."""

    def __init__(self, workdir, tty_type):
        self.workdir = Path(workdir)
        self.active = tty_type == "2"
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        os.set_blocking(self.master, False)
        port = os.ttyname(self.slave)
        self.log_file = (self.workdir / "stderr.log").open("wb")
        (self.ready, ready_write) = os.pipe()
        try:
            self.proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    LAUNCHER,
                    str(ready_write),
                    port,
                    str(SEMONITOR),
                    "-vvv",
                    "-x",
                    "-t",
                    tty_type,
                    "-r",
                    "out.rec",
                    "-o",
                    "out.json",
                    port,
                ],
                cwd=self.workdir,
                env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self.log_file,
                pass_fds=(ready_write,),
            )
        finally:
            os.close(ready_write)

    def wait_until_open(self):
        opened = select.select([self.ready], [], [], DEADLINE)[0]
        assert opened and os.read(self.ready, 1), (
            f"semonitor did not open the port\n{self.log}"
        )

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for fd in (self.ready, self.master, self.slave):
            if fd is not None:
                os.close(fd)
        self.log_file.close()

    @property
    def log(self):
        return (self.workdir / "stderr.log").read_text(errors="replace")

    def rejected(self, kinds):
        return any(kind in self.log for kind in kinds)

    def received(self):
        return (self.workdir / "out.rec").read_bytes()

    def output(self):
        path = self.workdir / "out.json"
        data = path.read_bytes() if path.exists() else b""
        return data[: data.rfind(b"\n") + 1].splitlines(keepends=True)

    def _alive(self):
        returncode = self.proc.poll()
        assert returncode is None, (
            f"semonitor ended early ({returncode})\n{self.log}"
        )

    def _wait_for(self, what, done):
        end = time.monotonic() + DEADLINE
        while not done():
            if self.proc.poll() is not None and not done():
                self._alive()
            assert time.monotonic() < end, f"{what}\n{self.log}"
            time.sleep(0.02)

    def send(self, data):
        view = memoryview(data)
        end = time.monotonic() + DEADLINE
        while view:
            self._alive()
            assert time.monotonic() < end, f"data not taken\n{self.log}"
            if select.select([], [self.master], [], 0.1)[1]:
                try:
                    view = view[os.write(self.master, view[:512]) :]
                except BlockingIOError:
                    pass

    def _queued(self):
        queued = fcntl.ioctl(self.slave, termios.FIONREAD, b"\0" * 4)
        return struct.unpack("i", queued)[0]

    def wait_until_taken(self):
        """Wait until the reader has taken all that was sent.

        What it has not taken is lost when the port is unplugged.
        """
        quiet = 0
        end = time.monotonic() + DEADLINE
        while quiet < 4:
            self._alive()
            assert time.monotonic() < end, f"data not taken\n{self.log}"
            quiet = 0 if self._queued() else quiet + 1
            time.sleep(0.005)

    def send_in_chunks(self, data, cuts):
        """Send data in pieces, each one taken before the next is sent."""
        start = 0
        for cut in [*sorted(cuts), len(data)]:
            self.send(data[start:cut])
            self.wait_until_taken()
            start = cut

    def wait_for_output(self, lines):
        self._wait_for(
            f"fewer than {lines} lines of JSON",
            lambda: len(self.output()) >= lines,
        )

    def unplug(self):
        os.close(self.master)
        self.master = None

    def wait_for_exit(self, seconds):
        try:
            return self.proc.wait(seconds)
        except subprocess.TimeoutExpired:
            return None

    def finish(self):
        """Unplug the port, and wait for the end of semonitor."""
        self.wait_until_taken()
        self.unplug()
        if self.active:
            # Waits for a Ctrl-C when the read thread has nothing to read.
            self._wait_for(
                "the end of the data was not noticed",
                lambda: (
                    self.proc.poll() is not None or "End of file" in self.log
                ),
            )
            self.proc.send_signal(signal.SIGINT)
        assert self.wait_for_exit(DEADLINE) is not None, (
            f"semonitor did not end\n{self.log}"
        )
        assert "Traceback" not in self.log, self.log
        # RS232 is always active, RS485 only listens.
        assert ("starting read thread" in self.log) is self.active, self.log


@pytest.fixture
def serial_run(workdir):
    runs = []

    def start(tty_type):
        runs.append(SerialSemonitor(workdir, tty_type))
        runs[-1].wait_until_open()
        return runs[-1]

    yield start
    for run in runs:
        run.close()


class Recording:
    """The frames of a recording, and the JSON that they become."""

    def __init__(self, data, lines):
        assert data.startswith(MAGIC)
        self.frames = data.split(MAGIC)[1:]
        self.lines = lines

    def unit(self, index):
        return MAGIC + self.frames[index]

    def stream(self, replace=None, *, upto=None):
        replace = replace or {}
        frames = range(len(self.frames) if upto is None else upto)
        return b"".join(replace.get(i, self.unit(i)) for i in frames)

    def json(self, lost=(), upto=None):
        frames = range(len(self.frames) if upto is None else upto)
        return [
            self.lines[JSON_FRAMES[i]]
            for i in frames
            if i in JSON_FRAMES and i not in lost
        ]


@pytest.fixture
def recording(golden):
    return Recording(
        golden("rec", SAMPLE).read_bytes(),
        golden("json", SAMPLE).read_bytes().splitlines(keepends=True),
    )


# RS232 is always active, which is checked at the end of each run.
TTY_TYPES = [
    "4",
    pytest.param("2", marks=pytest.mark.xfail(strict=True, reason="Issue #12")),
]


def flip(offset, mask=0x01):
    return lambda unit: (
        unit[: offset % len(unit)]
        + bytes([unit[offset] ^ mask])
        + unit[offset % len(unit) + 1 :]
    )


def drop(offset):
    return lambda unit: (
        unit[: offset % len(unit)] + unit[offset % len(unit) + 1 :]
    )


def insert(offset, value=0xA5):
    return lambda unit: (
        unit[: offset % len(unit)] + bytes([value]) + unit[offset % len(unit) :]
    )


# A unit is the magic (0-3), length (4-5), inverse length (6-7), sequence
# (8-9), source (10-13), destination (14-17), function (18-19), the data and
# the checksum (the last 2 bytes).
FIRST_DATA = 20
IN_THE_DATA = 60
LAST_DATA = -3
CHECKSUM_LOW = -2
CHECKSUM_HIGH = -1

# These move the end of the frame, or the next magic number: RS485 reads up
# to the next magic number, so the frame is lost, and none of the others.
FLIPPED_MAGIC = [
    pytest.param(flip(0, 0x01), id="flip-magic-0"),
    pytest.param(flip(1, 0x80), id="flip-magic-1"),
    pytest.param(flip(2, 0x10), id="flip-magic-2"),
    pytest.param(flip(3, 0x08), id="flip-magic-3"),
]

FRAMING_FAULTS = [
    *[pytest.param(*f.values, EXTRA_BYTES, id=f.id) for f in FLIPPED_MAGIC],
    pytest.param(drop(1), EXTRA_BYTES, id="drop-magic"),
    pytest.param(flip(4, 0x01), LENGTH_ERRORS, id="flip-length"),
    pytest.param(flip(7, 0x80), LENGTH_ERRORS, id="flip-inverse-length"),
    pytest.param(drop(8), LENGTH_ERRORS, id="drop-header"),
    pytest.param(drop(IN_THE_DATA), LENGTH_ERRORS, id="drop-data"),
    pytest.param(drop(CHECKSUM_HIGH), LENGTH_ERRORS, id="drop-checksum"),
    pytest.param(insert(8), CHECKSUM_ERRORS, id="insert-header"),
    pytest.param(insert(IN_THE_DATA), CHECKSUM_ERRORS, id="insert-data"),
]

# These leave the frames where they are, for RS232 as well.
FIELD_FAULTS = [
    pytest.param(flip(8, 0x40), CHECKSUM_ERRORS, id="flip-sequence"),
    pytest.param(flip(10, 0x01), CHECKSUM_ERRORS, id="flip-source"),
    pytest.param(flip(17, 0x80), CHECKSUM_ERRORS, id="flip-destination"),
    pytest.param(flip(19, 0x02), CHECKSUM_ERRORS, id="flip-function"),
    pytest.param(flip(FIRST_DATA), CHECKSUM_ERRORS, id="flip-first-data"),
    pytest.param(flip(IN_THE_DATA, 0x20), CHECKSUM_ERRORS, id="flip-data"),
    pytest.param(flip(LAST_DATA, 0x80), CHECKSUM_ERRORS, id="flip-last-data"),
    pytest.param(flip(CHECKSUM_LOW), CHECKSUM_ERRORS, id="flip-checksum-low"),
    pytest.param(flip(CHECKSUM_HIGH), CHECKSUM_ERRORS, id="flip-checksum-high"),
]

NOISE = [
    pytest.param(bytes(range(0x80, 0xA0)), id="noise"),
    pytest.param(b"\x00" * 64, id="line-held-low"),
    pytest.param(b"\xff" * 64, id="line-held-high"),
]


def converted(run, recording, stream, **expected):
    """Send the stream, pull the cable and check what came out."""
    run.send(stream)
    run.finish()
    assert run.output() == recording.json(**expected)


@pytest.mark.parametrize("tty_type", TTY_TYPES)
def test_nothing_on_the_line_ends_without_output(serial_run, tty_type):
    run = serial_run(tty_type)

    run.finish()

    assert run.output() == []
    assert not run.received()
    assert not run.rejected(ANY_ERROR)


@pytest.mark.parametrize("tty_type", TTY_TYPES)
def test_the_recording_is_converted(serial_run, recording, tty_type):
    run = serial_run(tty_type)
    stream = recording.stream()

    converted(run, recording, stream)

    assert run.received() == stream
    assert not run.rejected(ANY_ERROR)


@pytest.mark.parametrize("tty_type", TTY_TYPES)
@pytest.mark.parametrize(
    "cut",
    [
        pytest.param(2, id="2-bytes-in"),
        pytest.param(4, id="4-bytes-in"),
        pytest.param(10, id="10-bytes-in"),
        pytest.param(20, id="20-bytes-in"),
        pytest.param(-3, id="3-bytes-before-the-end"),
        pytest.param(-1, id="1-byte-before-the-end"),
    ],
)
def test_the_data_is_converted_whatever_the_chunks(
    serial_run, recording, tty_type, cut
):
    run = serial_run(tty_type)
    stream = recording.stream()
    cuts = []
    for index in range(len(recording.frames)):
        unit = recording.unit(index)
        cuts.append(len(recording.stream(upto=index)) + cut % len(unit))

    run.send_in_chunks(stream, cuts)
    run.finish()

    assert run.output() == recording.json()
    assert run.received() == stream
    assert not run.rejected(ANY_ERROR)


# A message without a length (RS485) ends with the next magic number. The
# port stays open: waiting for more bytes than the message has, to fill a
# buffer, would hold the message back for ever.
@pytest.mark.parametrize("tty_type", TTY_TYPES)
def test_a_message_is_converted_without_waiting_for_more(
    serial_run, recording, tty_type
):
    run = serial_run(tty_type)

    run.send(recording.stream(upto=FIRST + 1) + MAGIC)
    run.wait_for_output(1)

    assert run.output() == recording.json(upto=FIRST + 1)
    run.finish()
    assert not run.rejected(ANY_ERROR)


@pytest.mark.parametrize(("fault", "errors"), [*FRAMING_FAULTS, *FIELD_FAULTS])
def test_a_damaged_frame_is_lost_and_the_rest_is_converted(
    serial_run, recording, fault, errors
):
    run = serial_run("4")
    stream = recording.stream({TARGET: fault(recording.unit(TARGET))})

    converted(run, recording, stream, lost={TARGET})

    assert run.rejected(errors), run.log
    assert run.received() == stream


@pytest.mark.xfail(strict=True, reason="Issue #12")
@pytest.mark.parametrize(("fault", "errors"), FIELD_FAULTS)
def test_a_damaged_frame_is_lost_and_the_rest_is_converted_on_rs232(
    serial_run, recording, fault, errors
):
    run = serial_run("2")
    stream = recording.stream({TARGET: fault(recording.unit(TARGET))})

    converted(run, recording, stream, lost={TARGET})

    assert run.rejected(errors), run.log
    assert run.received() == stream


# What is not a magic number does not tell the end of the message before.
@pytest.mark.parametrize("noise", NOISE)
def test_noise_between_the_frames_is_not_a_frame(serial_run, recording, noise):
    run = serial_run("4")
    stream = recording.stream({TARGET: recording.unit(TARGET) + noise})

    converted(run, recording, stream)

    assert run.received() == stream
    assert not run.rejected(ANY_ERROR)


@pytest.mark.parametrize("noise", NOISE)
def test_noise_before_the_first_frame_is_skipped(serial_run, recording, noise):
    run = serial_run("4")
    stream = noise + recording.stream()

    converted(run, recording, stream)

    assert run.received() == stream
    assert not run.rejected(ANY_ERROR)


@pytest.mark.parametrize("tty_type", TTY_TYPES)
@pytest.mark.parametrize(
    ("cut", "errors"),
    [
        pytest.param(2, None, id="inside-the-magic"),
        pytest.param(4, None, id="after-the-magic"),
        pytest.param(10, None, id="inside-the-header"),
        pytest.param(20, TRUNCATED, id="after-the-header"),
        pytest.param(IN_THE_DATA, TRUNCATED, id="inside-the-data"),
        pytest.param(CHECKSUM_HIGH, TRUNCATED, id="inside-the-checksum"),
    ],
)
def test_a_frame_cut_off_by_the_end_of_the_line_is_lost(
    serial_run, recording, tty_type, cut, errors
):
    run = serial_run(tty_type)
    unit = recording.unit(LAST)
    stream = recording.stream(upto=LAST) + unit[: cut % len(unit)]

    converted(run, recording, stream, upto=LAST)

    # RS232 only records what it has read whole, so not a cut off message.
    assert stream.startswith(run.received())
    if not run.active:
        assert run.received() == stream
    if errors:
        assert run.rejected(errors), run.log


# The 4 byte integer of the first meter, that is 0 in the recording, is
# the magic number (0x79563412, as the bytes are in little endian order).
def with_the_magic_in_the_data(recording):
    frame = recording.frames[TARGET]
    (length, _, sequence, source, destination, function) = struct.unpack(
        "<HHHLLH", frame[:16]
    )
    data = bytearray(frame[16 : 16 + length])
    assert data[8 + 22 : 8 + 26] == bytes(4)
    data[8 + 22 : 8 + 26] = MAGIC
    return MAGIC + bytes(
        se.msg.formatMsg(sequence, source, destination, function, bytes(data))
    )


@pytest.mark.parametrize(
    "tty_type",
    [
        pytest.param(
            "4", marks=pytest.mark.xfail(strict=True, reason="Issue #60")
        ),
        pytest.param(
            "2", marks=pytest.mark.xfail(strict=True, reason="Issue #12")
        ),
    ],
)
def test_a_frame_with_the_magic_in_its_data_is_one_frame(
    serial_run, recording, tty_type
):
    run = serial_run(tty_type)
    unit = with_the_magic_in_the_data(recording)
    assert unit.count(MAGIC) == 2
    stream = recording.stream({TARGET: unit})
    expected = recording.json()
    expected[JSON_FRAMES[TARGET]] = expected[JSON_FRAMES[TARGET]].replace(
        b'"Totaloff22_int4": 0', b'"Totaloff22_int4": 2035692562', 1
    )

    run.send(stream)
    run.finish()

    assert run.output() == expected
    assert run.received() == stream
    assert not run.rejected(ANY_ERROR)


# The length of the frame is all that RS232 has to find the next frame, so
# a frame that does not have that length loses all the frames after it.
@pytest.mark.xfail(strict=True, reason="Issue #61")
@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(drop(IN_THE_DATA), id="drop-data"),
        pytest.param(insert(IN_THE_DATA), id="insert-data"),
        pytest.param(flip(4, 0x01), id="flip-length"),
    ],
)
def test_rs232_finds_the_next_frame_after_a_lost_one(
    serial_run, recording, fault
):
    run = serial_run("2")
    stream = recording.stream({TARGET: fault(recording.unit(TARGET))})

    converted(run, recording, stream, lost={TARGET})


@pytest.mark.xfail(strict=True, reason="Issue #62")
@pytest.mark.parametrize("fault", FLIPPED_MAGIC)
def test_rs232_does_not_take_a_frame_without_the_magic_number(
    serial_run, recording, fault
):
    run = serial_run("2")
    stream = recording.stream({TARGET: fault(recording.unit(TARGET))})

    converted(run, recording, stream, lost={TARGET})

    assert run.received() == stream


# A port that is lost is a failure, so that a container is restarted, or
# the user notices. The unplugged port is how the other tests end the data.
@pytest.mark.xfail(strict=True, reason="Issue #64")
def test_a_lost_rs485_port_is_a_failure(serial_run):
    run = serial_run("4")

    run.unplug()

    assert run.wait_for_exit(EXIT_WAIT) not in (None, 0), run.log


@pytest.mark.xfail(strict=True, reason="Issue #65")
def test_a_lost_rs232_port_is_a_failure(serial_run):
    run = serial_run("2")

    run.unplug()

    assert run.wait_for_exit(EXIT_WAIT) not in (None, 0), run.log
