import importlib.util
import logging
import logging.handlers
import os
from pathlib import Path
import socket
import stat

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent / "conversion" / "seWindowsSyslog.py"
)


# The hook that logging calls to open the file of the handler.
def open_stream(handler):
    return handler._open()  # noqa: SLF001  # the hook of the logging module


# Load the module, with its logging set up thrown away afterwards. The module
# sends its messages with a SysLogHandler, which, by default, wants a unix
# socket at /dev/log, which is not there in a test.
@pytest.fixture
def module(monkeypatch):
    sockets = []

    class Recorder:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.sent = []
            sockets.append(self)

        def connect(self, *args):
            pass

        def send(self, data):
            self.sent.append(data)

        def sendto(self, data, *args):
            self.sent.append(data)

        def close(self):
            pass

        def setsockopt(self, *args):
            pass

    monkeypatch.setattr(socket, "socket", Recorder)
    logger = logging.getLogger("syslog")
    handlers = logger.handlers[:]
    level = logger.level
    spec = importlib.util.spec_from_file_location(
        "seWindowsSyslog_under_test", SCRIPT
    )
    loaded = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(loaded)
        loaded.sockets = sockets
        yield loaded
    finally:
        for handler in logger.handlers[:]:
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(level)


# --- syslog replacement ------------------------------------------------------


def test_syslog_is_the_info_method_of_the_syslog_logger(module):
    assert module.syslog == module.my_logger.info
    assert module.my_logger.name == "syslog"


def test_the_logger_passes_everything_down_to_debug(module):
    assert module.my_logger.level == logging.DEBUG


def test_the_logger_has_a_syslog_handler(module):
    assert any(
        isinstance(handler, logging.handlers.SysLogHandler)
        for handler in module.my_logger.handlers
    )


def test_a_message_is_formatted_with_time_level_and_text(module):
    record = logging.LogRecord(
        "syslog", logging.INFO, __file__, 1, "an emulated message", None, None
    )

    formatted = module.handler.formatter.format(record)

    assert formatted.endswith("INFO     an emulated message")


def test_the_level_name_is_padded_to_eight_characters(module):
    record = logging.LogRecord(
        "syslog", logging.ERROR, __file__, 1, "x", None, None
    )

    assert " ERROR    x" in module.handler.formatter.format(record)


def test_syslog_calls_end_up_at_the_handler(module):
    module.syslog("Hello %s", "world")

    sent = b"".join(data for sock in module.sockets for data in sock.sent)
    assert b"Hello world" in sent


def test_importing_has_no_output_and_does_not_log(module, capsys):
    assert capsys.readouterr().out == ""


# --- rotating file handler ---------------------------------------------------


@pytest.fixture
def rotating(module, workdir):
    handler = module.TimedRotatingFileHandlerUmasked(
        str(workdir / "log"), when="midnight", backupCount=3
    )
    yield handler
    handler.close()


def test_the_log_file_is_created_group_writable(module, workdir):
    handler = module.TimedRotatingFileHandlerUmasked(
        str(workdir / "fresh.log"), when="midnight", delay=True
    )
    previous = os.umask(0o022)
    try:
        open_stream(handler).close()
    finally:
        os.umask(previous)
        handler.close()

    mode = stat.S_IMODE((workdir / "fresh.log").stat().st_mode)
    assert mode & 0o060 == 0o060


def test_the_umask_is_restored_after_opening(rotating):
    previous = os.umask(0o027)
    try:
        open_stream(rotating).close()
        current = os.umask(previous)
    except BaseException:
        os.umask(previous)
        raise

    assert current == 0o027


@pytest.mark.xfail(strict=True, reason="Issue #30")
def test_the_umask_is_restored_when_opening_fails(module, workdir):
    handler = module.TimedRotatingFileHandlerUmasked(
        str(workdir / "log"), when="midnight", delay=True
    )
    handler.baseFilename = str(workdir / "no-such-dir" / "log")
    previous = os.umask(0o027)
    try:
        with pytest.raises(OSError):
            open_stream(handler)
        current = os.umask(previous)
    except BaseException:
        os.umask(previous)
        raise
    finally:
        handler.close()

    assert current == 0o027


@pytest.mark.xfail(strict=True, reason="Issue #30")
def test_a_failure_to_open_is_not_swallowed(module, workdir):
    handler = module.TimedRotatingFileHandlerUmasked(
        str(workdir / "log"), when="midnight", delay=True
    )
    handler.baseFilename = str(workdir / "no-such-dir" / "log")

    try:
        with pytest.raises(OSError):
            open_stream(handler)
    finally:
        handler.close()
