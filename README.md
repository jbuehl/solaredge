# SolarEdge Monitoring

[![CI](https://github.com/centraluniverse/semonitor/actions/workflows/test.yml/badge.svg)](https://github.com/centraluniverse/semonitor/actions/workflows/test.yml)


This project enables monitoring the performance data of SolarEdge inverters and
optimizers. Solaredge supports the open Sunspec Alliance logging protocols,
however this data is only accessible via an RS485 interface on the inverter and
does not include module level (optimizer) data. Solaredge publishes an API that
allows access to their portal, however this also does not include module level
data.


**! ! ! ! ! ! ! ! ! ! ! ! November 2026 update ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! !**

The ethernet (network) modes that were kept in September 2025 are now gone as
well. Inverters with up to date firmware talk to the SolarEdge portal using TLS,
which cannot be intercepted, so there is nothing left for these modes to capture
or answer.

Removed are the active and passive ethernet modes, which includes the `-t n`
data source type, the `-p` option to select the ports to listen on and all of
the network code.

Still supported are RS232 (active) and RS485 (active and passive), plus reading
a recorded file or `stdin`.


**! ! ! ! ! ! ! ! ! ! ! ! September 2025 update ! ! ! ! ! ! ! ! ! ! ! ! ! ! !**

Support for the SolarEdge homegrown encryption has been removed, as has the
local DHCP/DNS server. Ethernet active and passive modes are still supported
assuming that the inverter has old firmware that does not do encryption and it
is not communicating with the actual SolarEdge server.


**! ! ! ! ! ! ! ! ! ! ! ! September 2023 update ! ! ! ! ! ! ! ! ! ! ! ! ! ! !**

When this project was started ten years ago, SolarEdge inverters communicated
with their monitoring server using a proprietary data format that was sent in
the clear. It was possible to reverse engineer most of the messages in order
to obtain the optimizer level data which was not otherwise available. The same
data was also available on the RS232 and RS485 interfaces which were provided
on their inverters. A few years later, SolarEdge implemented a homegrown
encryption algorithm for the communications to their monitoring server, which
prevented access for a while until an effort by a number of contributors to
this project was successful in figuring out the algorithm which got it working
again.

In the years since then, SolarEdge has introduced new products which no longer
support the RS232 interface, and they have dropped their encryption algorithm
and are now using the far more secure and mainstream SSL/TLS encryption method
which is essentially not hackable. This means that if you have a newer inverter
or if the firmware in your older inverter is up to date, the only way to access
performance data is going to be via the RS485 interface.

Also, please note that this software is made available here without any
expectation of support. If you use it and have a problem that you can't solve,
you can open an issue, however there may not be a response, given the relatively
small number of contributors and the fact that SolarEdge does not support this
project in any way. Contributors are only familiar with the particular SolarEdge
equipment that they personally own and are not motivated to maintain the software
beyond their particular needs.


**! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! !**


## How it works

SolarEdge inverter monitoring data can be accessed by either of 2 hardware
interfaces - RS232 or RS485. Data can be parsed by semonitor.py either in an
active mode, where semonitor.py interacts with the inverter directly, or in a
passive mode where the data that is being exchanged on the bus is monitored.

```text
interface    modes
---------    -----
RS232        active
RS485        active, passive
```


### Access modes


#### RS485 active

The server running `semonitor.py` is connected to one or more inverters through
a serial port with an RS485 adapter. All inverters must be configured as RS485
slaves and `semonitor.py` functions as the RS485 master. The inverter serial
numbers are specified to `semonitor.py` using the `-s` option and the `-m`
option specifies master mode. There cannot be another master device on the RS485
bus.

The server running semonitor.py is connected to one or more inverters through a
serial port with an RS485 adapter. Some other device such as an inverter or a SolarEdge
Control and Communication Gateway functions as the RS485 master and semonitor.py
just monitors the data on the bus. Depending on capability of the hardware running
semonitor.py, there may be issues with it being able to keep up with the data rate
so there may be lost or corrupted data.


#### RS485 passive

The server running `semonitor.py` is connected to one or more inverters through
a serial port with an RS485 adapter. Some other device such as an inverter or a
SolarEdge Control and Communication Gateway functions as the RS485 master and
`semonitor.py` just monitors the data on the bus. Depending on capability of the
hardware running `semonitor.py`, there may be issues with it being able to keep
up with the data rate so there may be lost or corrupted data.


#### RS232 active

RS232 is a point to point interface so only active mode is meaningful. While it
is technically possible to capture RS232 traffic into a file and process the
file using `semonitor.py`, that is out of scope of this discussion.

Specified commands may be sent to the inverter from `semonitor.py` using the
`-c` option over either of the 2 hardware interfaces, but there are certain
commands that the inverter will only accept when coming from the RS232
interface. If an inverter is in encrypted mode, commands to get the encryption
key or to place the inverter in unencrypted mode must be sent over RS232.


### Hardware configurations


#### RS485 Active

```text
inverter ---
            |
            |
            |     semonitor
inverter -------- server
            |
            |
            |
inverter ---
```


#### RS485 Passive

```text
                  RS485
inverter -------- master
            |
            |
            |     semonitor
inverter -------- server
            |
            |
            |
inverter ---
```


### RS232 active

```text
                  semonitor
inverter -------- server

```


## How to use it

This describes how to use the programs.


`semonitor.py` is a program that implements a subset of the SolarEdge
protocol. It can be used to parse the performance data that has been previously
captured to a file, or it can interact directly with a SolarEdge inverter over
the RS232 or RS485 interface. Performance data is output to a file in JSON
format.

`seprint.py` prints a subset of data in human readable form from a file
containing JSON performance data.

`se2state.py` follows a file containing JSON performance data and outputs a
JSON file that contains the current state of the inverter and optimizer values.

`se2csv.py` reads a file containing JSON performance data and outputs a
separate comma delimited file for each device type (eg inverter, optimizer,
battery) encountered that is suitable for input to a spreadsheet.

`se2graphite.py` and `pickle2graphite.py` both read a file containing JSON
performance data and send it to a graphite server `se2graphite.py` sends it to
the graphite server's "text listener" port one metric at a time, while
`pickle2graphite.py` sends it to the graphite server's "pickle listener" port,
with multiple metrics per transmission.


### JSON format

semonitor.py writes one JSON object per line (JSON Lines) for every message
that carries performance data, with the keys sorted. Every line has the
sections `events`, `inverters` and `optimizers`, which are empty (`{}`) when
there is nothing to report, and devices that are not (fully) decoded get a
section of their own, such as `meters_0x0022` or `Unknown_device_0x0017`. How
the devices are nested in those sections is described in
[README.ParseDevice.md](README.ParseDevice.md#the-json-lines-of-semonitor).


The only deviation from standard JSON (RFC 8259) is that numbers can be `NaN`,
`Infinity` and `-Infinity` (in practice only `NaN` is seen, for values that are
not valid), which Python's `json` module reads and writes by default
(`allow_nan=True`). A strict parser, such as `JSON.parse`, refuses these. In
Python, `json.loads(line)` just works, and `json.loads(line,
parse_constant=...)` can be used to turn them into something else


### semonitor.py

SolarEdge inverter performance monitoring using the SolarEdge protocol.


#### Usage

```sh
    python semonitor.py [options] [datasource]
```


#### Arguments

```text
    datasource       Input filename or serial port.

                     If no data source is specified, the program reads from
                     stdin.

                     If a file name is specified, the program processes the
                     data in that file and terminates, unless the -f option
                     is specified, in which case it waits for further data
                     to be written to the file.

                     If the data source corresponds to a serial port,
                     send commands to and process the data from that por.
```


#### Options

```text
    -a                   append to output file if the file exists
    -b                   baud rate for serial data source (default: 115200)
    -c cmd[/cmd/...]     send the specified command functions
    -d debugfile         where to send debug messages (stdout|syslog|filename)
                         (default: syslog)
    -f                   wait for appended data as the input file grows
                         (as in tail -f)
    -m                   function as a RS485 master
    -o outfile           write performance data to the specified file in
                         JSON format (default: stdout)
    -r recfile           file to record all incoming and outgoing messages to
    -s inv[,inv,...]     comma delimited list of SolarEdge slave inverter IDs
    -t 2|4               data source type (2=RS232, 4=RS485)
    -u updatefile        file to write firmware update to (experimental)
    -v                   verbose output
    -x                   halt on data exception
```


#### Notes

Data may be read from a file containing messages in the raw SolarEdge protocol
such as the parsed output of a packet capture or the output from a previous run
of semonitor.py. It may also be read in real time from one of the RS232 or
RS485 interfaces on a SolarEdge inverter.

This program expects the data to be in SolarEdge format A pcap file contains
additional data that `semonitor.py` can't interpret. If you wish to read data
from a pcap file, you should filter out the SolarEdge data using utility such
as tshark:
`tshark -r infile.pcap -T fields -e data | xxd -r -p | ./semonitor.py -`

Debug messages are sent to the system log, unless the `-d` option is specified.
If an error occurs while processing data, the program will log a message and
continue unless the `-x` option is specified.

The level of debug messaging is controlled using the `-v` option, which may be
specified up to 4 times:

```text
    -v      log input parameters and file operations
    -vv     log incoming and outgoing messages
    -vvv    log the parsed data of incoming and outgoing messages
    -vvvv   log the raw data of incoming and outgoing messages
```

Messages logged at the `-vv` level and above contain the device or file sending
or receiving the message, the direction it was sent, the message size, and a
sequence number. Separate sequences are kept for incoming and outgoing messages.

The `-t` option is used to specify the data source type for non-file input. If
the data source is a serial port, the `-t` option must be included with either
the values 2 or 4 to specify whether it is connected to the RS232 or RS485 port.

The `-c`, `-m`, and `-s` options are not vaild if input is from a file or
`stdin`.

The `-m` option is only valid if a serial port is specified, and one or more
inverter IDs must be specified with the `-s` option. If this option is
specified, there cannot be another master device on the RS485 bus.
`semonintor.py` will repeatedly send commands to the specified inverters to
request performance data.

The `-c` option may be specified for a serial device. The option specifies one
or more SolarEdge protocol command functions separated by a "/". Each command
function consists of a hex function code followed by zero or more comma
separated hex parameters. Each parameter must begin with one of the letters "B",
"H", or "L" to designate the length of the parameter:

```text
    B = 8 bits
    H = 16 bits
    L = 32 bits
```

All function codes and parameters must be hexadecimal numbers, without the
leading "0x". Exactly one inverter ID must be specified with the `-s` option.
After each command is sent, `semonitor.py` will wait for a response before
sending the next command. When all commands have been sent and responded to, the
program terminates. Responses are sent to output.

Commands initiated by `semonitor.py` as the result of the `-c` or `-m` options
need to maintain a monotonically increasing sequence number which is used as a
transaction ID. A file named `seseq.dat` will be created to persist the value of
this sequence number across multiple executions of `semonitor.py`.


A recording can also be read through a serial port, without an inverter, to try
`semonitor.py` the way it runs in production. `socat` can make a pseudo
terminal for this. `semonitor.py` only accepts a port that the operating system
lists as a serial port, which are the names that start with `/dev/ttyS`,
`/dev/ttyUSB` or `/dev/ttyACM`, so the pseudo terminal has to be linked under
such a name in `/dev`, which needs root. Use a name that no real port has, such
as `/dev/ttySE0`:

```sh
    socat -u 'SYSTEM:sleep 5; cat recording.rec; sleep 10' \
        pty,raw,echo=0,link=/dev/ttySE0
```

Start `semonitor.py -t 4 /dev/ttySE0` within those 5 seconds. Data that arrives
before the port is opened is thrown away, and so is data that has not been read
yet when `socat` ends, so the last `sleep` has to be long enough for all of it
to be read.


#### Examples

```sh
    python semonitor.py -o yyyymmdd.json yyyymmdd.dat
```

Read from SE data file `yyyymmdd.dat` and write data to the json file
`yyyymmdd.json`.

```sh
    python semonitor.py -o yyyymmdd.json -m -s 7f101234,7f105678 -t 4 COM4
```

Function as a RS485 master to request data from the inverters `7f101234` and
`7f105678` using RS485 serial port COM4.

```sh
    python semonitor.py -c 0012,H0329 -s 7f101234 -t 2 /dev/ttyUSB0
```

Send a command to the inverter `7f101234` to request the value of parameter
`0x0329` using RS232 serial port /dev/ttyUSB0. Display the messages on stdout.

```sh
    python semonitor.py -c 0011,H329,L0/0030,H01f4,L0 -s 7f101234 -t 2 /dev/ttyUSB0
```

Send commands to the inverter `7f101234` to set the value of parameter `0x0329`
to `0`, followed by a command to reset the inverter using RS232 serial port
`/dev/ttyUSB0`. Display the debug messages on stdout.


### seextract.py

This program was intended to extract the TCP stream containing the SolarEdge
data from a PCAP file. Because it had issues and there exists a number of open
source utilities that perform that function it was removed from the project.

* tshark - <https://www.wireshark.org/docs/man-pages/tshark.html>
* PcapSplitter - <https://github.com/seladb/PcapPlusPlus/tree/master/Examples/PcapSplitter>
* tcpflow - <https://github.com/simsong/tcpflow>
* SplitCap - <https://www.netresec.com/?page=SplitCap>


### se2state.py

Maintain a JSON file containing the current state of SolarEdge inverters and
optimizers.


#### Usage

```sh
    python se2state.py options [inFile]
```


#### Arguments

```text
    inFile          File containing performance data in JSON format. (default:
                    stdin)
                    The program will follow (wait for new data to be written to)
                    the file.
```


#### Options

```text
    -i inverter[,inverter...] Initialize the state file using the specified inverter
                    IDs rather than using an existing one.
    -o stateFile    File containing the current (last read) data values for each
                    inverter and optimizer values from the input file. It will
                    be overwritten every time that new data is read.
```


#### Examples

Passively read the RS485 bus from the serial port /dev/ttyUSB0. Send performance
data to the file yyyymmdd.json and also maintain the file solar.json with the
current state.

```sh
    python semonitor.py -t n | tee yyyymmdd.json | python se2state.py -o solar.json
```

Accept connections from inverters over the network. Send performance data to
the file `yyyymmdd.json` and also maintain the file`solar.json` with the current
state. The inverter acquires its IP address and resolves the server hostname by
a means other than `semonitor.py`.


### seprint.py

Print a subset of data from a file containing JSON performance data.


#### Usage

```sh
    python seprint.py [inFile]
```


#### Arguments

```text
    inFile          File containing JSON performance data from
                    an inverter output from semonitor.py. (default: stdin)
```


#### Examples

```sh
    python solaredge/seprint.py yyyymmdd.json
```


### se2csv.py

Convert SolarEdge inverter performance monitoring data from JSON to CSV.


#### Usage

```sh
    python se2csv.py options [inFile]
```


#### Arguments

```text
    inFile          File containing performance data in JSON format. (default:
                    stdin)
```


#### Options

```text
    -a              append to inverter and optimizer files
    -d delim        csv file delimiter (default: ",")
    -t              write column headers to csv files
    -p csvPrefix    prefix for all csv filenames
    -i invFile      deprecated - use -p instead
    -o optFile      deprecated - use -p instead
````


#### Examples

```sh
    python se2csv.py -p yyyymmdd -t yyyymmdd.json
```

Read from SE data file `yyyymmdd.json` and write CSV data with headers, for each
device type encountered (eg optimizers, inverters, batteries), to files called
`yyyymmdd."deviceType".csv`


### se2graphite.py

Send SolarEdge performance monitoring data from JSON to a graphite text port.


#### Usage

```sh
    python se2graphite.py options [inFile]
```


#### Arguments

```text
    inFile          File containing performance data in JSON format. (default:
                    stdin)
```


#### Options

```text
    -b base         base prefix for the names of the metrics sent to graphite
    -h host         the host url or IP address of the graphite server (default: "localhost")
    -p port         the port number of the graphite / carbon text listener port (default: 2003)
```


#### Examples

```sh
    python se2graphite.py -b "semonitor" yyyymmdd.json
```

Send all numeric metric data for each device encountered in `yyymmdd.json` to
the graphite server whose "text" port is listening on "localhost:2003".

Metrics are sent one value at a time, with a short delay (default 0.1 sec)
between each transmission.

In graphite / whisper all metric names will begin with "semonitor."


### pickle2graphite.py

Send SolarEdge performance monitoring data from JSON to a graphite pickle
listener port.


#### Usage

```sh
    python pickle2graphite.py options [inFile]
```


#### Arguments

```text
    inFile          File containing performance data in JSON format. (default: stdin)
```


#### Options

```text
    -b base         base prefix for the names of the metrics sent to graphite
    -h host         the host url or IP address of the graphite server (default: "localhost")
    -p port         the port number of the graphite / carbon pickle listener port (default: 2004)
    -f              follow (wait for new data to be written to) the JSON inFile
```


#### Examples

```sh
    python pickle2graphite.py -b "semonitor" yyyymmdd.json
```

Send all numeric metric data for each device encountered in `yyyymmdd.json` to
the graphite server whose "pickle" port is listening on "localhost:2004".

Each json line from the file is batched up into a pickled list of metrics,
so many metrics may be sent at the same time. There is a short delay (default
0.2 sec) between each transmission.

When running "in production" this delay usually seems to be adequate, but when a
large json file with many metrics which graphite hasn't seen before is sent to
graphite, the server may be swamped, and some metrics may be dropped. Either:

* just rerun `pickle2graphite.py` again, or
* temporarily adjust the delay to say 5.0 secs, or
* even use `se2graphite.py` once,

any of which should allow the graphite server enough time to create new whisper
files, before the next batch of metrics from the next line in the json file
arrives.

In graphite / whisper all metric names will begin with "semonitor."

If the `-f` option had been included, `pickle2graphite.py` would follow (wait
for new json lines to be written to) the inFile (`yyyymmdd.json`) until
interrupted (Ctrl-C) or otherwise killed.


## Development

To develop on semonitor, set up the virtualenv and git hook, and lint all
files, in one go:

```sh
    ./pre-commit.sh
```

Lint all files again, without the set up:

```sh
    .venv/bin/pre-commit run --all-files
```

Fix spelling mistakes interactively:

```sh
    .venv/bin/pre-commit run --hook-stage manual codespell-fix --all-files
```

Create a branch:

```sh
    git branch <title>
```

For an existing issue, the title could be the issue number.

Then commit and open a merge request!


## Testing

There are two kinds of tests, which both run in the pipeline:

* `test/test.sh` replays the recordings in `test/rec/` and compares the
  output with the golden data in `test/`. Never change or regenerate the
  golden data to make a test pass, a change of the output is a deliberate
  change of the golden data. This is our 'quick integration test'.
* `tests/` holds the [pytest][pytest] tests, which will try to do broad
  (unit)testing of all tools and also measures the coverage.

To run tests, use the wrapper script `run-tests.sh` which will pass any supplied
arguments to `pytest`.

```sh
./run-tests.sh
...
./run-tests.sh -k 'time' --exitfirst
```


[pytest]: https://docs.pytest.org/
