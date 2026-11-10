import ipaddress
import logging
from pathlib import Path
import runpy
import socketserver
import sys
from typing import ClassVar

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "utilities"
    / "tinyPythonSyslogServer.py"
)


# Give the script an untouched root logger, as basicConfig needs, and put
# everything back afterwards.
@pytest.fixture
def root_logging():
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield root
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


@pytest.fixture
def load(root_logging, monkeypatch):
    def run(run_name="tiny_syslog_server"):
        # pytest adds its own handlers to the root logger during the test, and
        # logging.basicConfig does nothing when there are handlers.
        for handler in root_logging.handlers[:]:
            root_logging.removeHandler(handler)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
        return runpy.run_path(str(SCRIPT), run_name=run_name)

    return run


def log_text(workdir):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (workdir / "logFiles" / "syslog.log").read_text()


class Handler:
    def __init__(self, handler_class, data, address=("192.0.2.7", 40000)):
        self.handler = handler_class.__new__(handler_class)
        self.handler.request = (data, object())
        self.handler.client_address = address

    def handle(self):
        self.handler.handle()


# --- set up ------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_the_log_directory_is_created_when_it_does_not_exist(workdir, load):
    load()

    assert (workdir / "logFiles").is_dir()


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_an_existing_log_directory_and_log_are_kept(
    workdir, load, root_logging
):
    (workdir / "logFiles").mkdir()
    (workdir / "logFiles" / "syslog.log").write_text("earlier message\n")

    namespace = load()
    Handler(namespace["SyslogUDPHandler"], b"new message").handle()

    assert log_text(workdir) == "earlier message\nnew message\n"


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_the_log_file_is_in_the_log_directory(load):
    namespace = load()

    assert namespace["LOG_FILE"] == f"{namespace['LOG_DIR']}/syslog.log"


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_the_server_listens_on_the_syslog_port_on_all_interfaces(load):
    namespace = load()

    assert namespace["PORT"] == 514
    assert namespace["HOST"] == str(ipaddress.IPv4Address(0))


# --- handler -----------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_a_message_is_logged_to_the_file_as_it_was_received(workdir, load):
    namespace = load()

    Handler(
        namespace["SyslogUDPHandler"], b"<13>Jan  1 12:00:00 host app: hello"
    ).handle()

    assert log_text(workdir) == "<13>Jan  1 12:00:00 host app: hello\n"


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_messages_are_appended_in_order(workdir, load):
    namespace = load()

    for text in (b"one", b"two", b"three"):
        Handler(namespace["SyslogUDPHandler"], text).handle()

    assert log_text(workdir).splitlines() == ["one", "two", "three"]


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_surrounding_whitespace_is_removed(workdir, load):
    namespace = load()

    Handler(namespace["SyslogUDPHandler"], b"  padded message \r\n").handle()

    assert log_text(workdir) == "padded message\n"


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_the_message_is_shown_with_the_address_of_the_sender(
    workdir, load, capsys
):
    namespace = load()

    Handler(
        namespace["SyslogUDPHandler"], b"hello", ("198.51.100.4", 5140)
    ).handle()

    out = capsys.readouterr().out
    assert "198.51.100.4" in out
    assert "hello" in out
    assert "5140" not in out


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_a_message_that_is_not_valid_utf8_is_still_logged(workdir, load):
    namespace = load()

    Handler(namespace["SyslogUDPHandler"], b"na\xefve broken \xff").handle()

    assert "broken" in log_text(workdir)


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_an_empty_message_does_not_break_the_handler(workdir, load):
    namespace = load()

    Handler(namespace["SyslogUDPHandler"], b"").handle()

    assert log_text(workdir) == "\n"


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_the_handler_is_a_datagram_request_handler(load):
    namespace = load()

    assert issubclass(
        namespace["SyslogUDPHandler"], socketserver.BaseRequestHandler
    )


# --- running it --------------------------------------------------------------


class FakeServer:
    created: ClassVar[list] = []
    action = None

    def __init__(self, address, handler):
        self.address = address
        self.handler = handler
        self.poll_interval = None
        FakeServer.created.append(self)

    def serve_forever(self, poll_interval=0.5):
        self.poll_interval = poll_interval
        if FakeServer.action is not None:
            raise FakeServer.action


@pytest.fixture
def fake_server(monkeypatch):
    FakeServer.created = []
    FakeServer.action = None
    monkeypatch.setattr(socketserver, "UDPServer", FakeServer)
    return FakeServer


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_main_serves_the_handler_on_the_configured_address(load, fake_server):
    namespace = load("__main__")

    (server,) = fake_server.created
    assert server.address == (namespace["HOST"], namespace["PORT"])
    assert server.handler is namespace["SyslogUDPHandler"]
    assert server.poll_interval == 0.5


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_importing_does_not_start_a_server(load, fake_server):
    load("tiny_syslog_server")

    assert fake_server.created == []


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_control_c_stops_the_server_with_a_message(load, fake_server, capsys):
    fake_server.action = KeyboardInterrupt()

    load("__main__")

    assert "Shutting down" in capsys.readouterr().out


@pytest.mark.xfail(strict=True, reason="Issue #17")
@pytest.mark.parametrize(
    "error", [PermissionError("port 514"), OSError("in use")]
)
def test_failing_to_bind_is_not_hidden(load, monkeypatch, error):
    def refuse(address, handler):
        raise error

    monkeypatch.setattr(socketserver, "UDPServer", refuse)

    with pytest.raises(type(error)):
        load("__main__")


@pytest.mark.xfail(strict=True, reason="Issue #17")
def test_a_system_exit_is_passed_on(load, fake_server):
    fake_server.action = SystemExit(3)

    with pytest.raises(SystemExit) as exit_:
        load("__main__")

    assert exit_.value.code == 3
