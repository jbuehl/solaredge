![CI](https://github.com/jbuehl/solaredge/actions/workflows/test.yml/badge.svg)

#### ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! !  September 2023 update ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! !
When this project was started ten years ago, SolarEdge inverters communicated with their monitoring server using a proprietary data format that was sent in the clear.  It was possible to reverse engineer most of the messages in order to obtain the optimizer level data which was not otherwise available.  The same data was also available on the RS232 and RS485 interfaces which were provided on their inverters.  A few years later, SolarEdge implemented a homegrown encryption algorithm for the communications to their monitoring server, which prevented access for a while until an effort by a number of contributors to this project was successful in figuring out the algorithm which got it working again.

In the years since then, SolarEdge has introduced new products which no longer support the RS232 interface, and they have dropped their encryption algorithm and are now using the far more secure and mainstream SSL/TLS encryption method which is essentially not hackable.  This means that if you have a newer inverter or if the firmware in your older inverter is up to date, the only way to access performance data is going to be via the RS485 interface.

Also, please note that this software is made available here without any expectation of support.  If you use it and have a problem that you can't solve, you can open an issue, however there may not be a response, given the relatively small number of contributors and the fact that SolarEdge does not support this project in any way.  Contributors are only familiar with the particular SolarEdge equipment that they personally own and are not motivated to maintain the software beyond their particular needs.

#### ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! !

SolarEdge Monitoring
====================
This project enables monitoring the performance data of SolarEdge inverters and optimizers.
Solaredge supports the open Sunspec Alliance logging protocols, however this data is only
accessible via an RS485 interface on the inverter and does not include module level (optimizer)
data.  Solaredge publishes an API that allows access to their portal, however this
also does not include module level data.

## How it works

SolarEdge inverter monitoring data can be accessed by any of 3 hardware interfaces -
ethernet, RS232, or RS485.  Data can be parsed by semonitor.py either in an active
mode, where semonitor.py interacts with the inverter directly, or in a passive mode
where the data that is being sent to the SolarEdge monitoring portal is captured.

```
interface    modes
---------    -----
ethernet     active, passive
RS232        active
RS485        active, passive
```

### Access modes

**Ethernet active**

The inverter is made to connect to semonitor.py instead of the SolarEdge monitoring
portal by resolving its hostname (usually prod.solaredge.com) to the IP address of
the server running semonitor.py.  This may be done by connecting the ethernet interface
of the inverter to a dedicated ethernet interface on the server running semonitor.py
and specifying the -n option which will run a simplified DHCP/DNS server that responds
to the inverter on the dedicated interface.  Alternatively, another DNS server in
the network could be made to resolve the address, but how to do that is beyond the
scope of this discussion.

In this mode, the inverter will no longer be communicating with the SolarEdge server
so monitoring services and firmware updates will no longer be available.

The encryption key for the inverter must first be obtained and given to semonitor.py
using the -k option, or the inverter must be set to unencrypted mode.  Either way,
this requires temporarily connecting via the RS232 interface.

**Ethernet passive**

Data sent between an inverter and the SolarEdge monitoring portal is captured and
fed into semonitor.py.  In order to do this the network traffic between them must
be monitored by a server on the network.  This will not work if the inverter and
the local server are connected to an ethernet switch.  Either they could be connected
through an ethernet hub, or the inverter could be connected to a dedicated network
interface on a server that bridges to the local network.

Traffic may be captured to a pcap file using wireshark or tcpdump or some other program.  
The resulting file must be processed through seextract.py before it is fed into
semonitor.py.  In this mode, semonitor.py is reading data from a file or stdin and
isn't actually reading from the network directly.

SolarEdge will place the inverter into encrypted mode, so semonitor.py will need
to be given the encryption key using the -k option.  The key must be accessed via
the RS232 interface.

**RS485 active**

The server running semonitor.py is connected to one or more inverters through a
serial port with an RS485 adapter.  All inverters must be configured as RS485 slaves
and semonitor.py functions as the RS485 master.  The inverter serial numbers are
specified to semonitor.py using the -s option and the -m option specifies master mode.  
There cannot be another master device on the RS485 bus.

**RS485 passive**

The server running semonitor.py is connected to one or more inverters through a
serial port with an RS485 adapter.  Some other device such as an inverter or a SolarEdge
Control and Communication Gateway functions as the RS485 master and semonitor.py
just monitors the data on the bus.  Depending on capability of the hardware running
semonitor.py, there may be issues with it being able to keep up with the data rate
so there may be lost or corrupted data.

**RS232 active**

RS232 is a point to point interface so only active mode is meaningful.  While it
is technically possible to capture RS232 traffic into a file and process the file
using semonitor.py, that is out of scope of this discussion.

Specified commands may be sent to the inverter from semonitor.py using the -c option
over any of the 3 hardware interfaces, but there are certain commands that the inverter
will only accept when coming from the RS232 interface.  If an inverter is in encrypted mode,
commands to get the encryption key or to place the inverter in unencrypted mode
must be sent over RS232.

### Hardware configurations

**Ethernet hardware configurations**

#### Active

```
                  semonitor
inverter -------- server

```

#### Passive using ethernet hub

```
                     capture
inverter ---     --- server
            |   |
           ethernet
             hub
              |
              |
              |
          SolarEdge
            server

```

#### Passive using dual capture server interfaces

```
                   capture
inverter --------- server ----
                              |
                              |
                              |
                          SolarEdge
                            server

```

**RS485 hardware configurations**
#### Active

```
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

#### Passive

```
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

**RS232 hardware configuration**

```
                  semonitor
inverter -------- server

```


## How to use it

This describes how to use the programs.

**semonitor.py** is a program that implements a subset of the SolarEdge protocol.  It can be
used to parse the performance data that has been previously captured to a file, or it can
interact directly with a SolarEdge inverter over the RS232, RS485, or ethernet interface.
Performance data is output to a file in JSON format.

**seextract.py** (removed)

**seprint.py** prints a subset of data in human readable form from a file containing JSON performance data.

**sekey.py** is used to extract the unique encryption key from an inverter.

**se2state.py** follows a file containing JSON performance data and outputs a JSON file
that contains the current state of the inverter and optimizer values.

**se2csv.py** reads a file containing JSON performance data and outputs a separate comma delimited
file for each device type (eg inverter, optimizer, battery) encountered that is suitable for input to a spreadsheet.

**se2graphite.py** and **pickle2graphite.py** both read a file containing JSON performance data
and send it to a graphite server.  se2graphite.py sends it to the graphite server's "text listener" port
one metric at a time, while pickle2graphite.py sends it to the graphite server's "pickle listener" port,
with multiple metrics per transmission.

### semonitor.py

SolarEdge inverter performance monitoring using the SolarEdge protocol.

#### Usage
    python semonitor.py [options] [datasource]

#### Arguments
    datasource           Input filename or serial port.

                         If no data source is specified, the program reads from
                         stdin, unless the data source type is specified as network.

                         If a file name is specified, the program processes the
                         data in that file and terminates, unless the -f option
                         is specified, in which case it waits for further data
                         to be written to the file.

                         If the data source corresponds to a serial port or network,
                         send commands to and process the data from that port or
                         network interface.

#### Options
    -a                   append to output file if the file exists
    -b                   baud rate for serial data source (default: 115200)
    -c cmd[/cmd/...]     send the specified command functions
    -d debugfile         where to send debug messages (stdout|syslog|filename)
                         (default: syslog)
    -f                   wait for appended data as the input file grows
                         (as in tail -f)
    -k keyfile           file containing a hex encoded encryption key
    -m                   function as a RS485 master
    -n interface         run DHCP and DNS network services on the specified
                         interface
    -o outfile           write performance data to the specified file in
                         JSON format (default: stdout)
    -p ports             ports to listen on in network mode
                         (default: 22222,22221,80)
    -r recfile           file to record all incoming and outgoing messages to
    -s inv[,inv,...]     comma delimited list of SolarEdge slave inverter IDs
    -t 2|4|n             data source type (2=RS232, 4=RS485, n=network)
    -u updatefile        file to write firmware update to (experimental)
    -v                   verbose output
    -x                   halt on data exception

#### Notes
Data may be read from a file containing messages in the raw SolarEdge protocol such as the parsed output
of a packet capture or the output from a previous run of semonitor.py.  It may also be
read in real time from one of the RS232, RS485, or ethernet interfaces on a SolarEdge inverter.

NOTE: This program expects the data to be in SolarEdge format.  A pcap file contains additional
data that semonitor.py can't interpret. If you wish to read data from a pcap file, you should filter
out the SolarEdge data using a utility such as tshark:
`tshark -r infile.pcap -T fields -e data | xxd -r -p | ./semonitor.py -`

Debug messages are sent to the system log, unless the -d option is specified.  If an error occurs
while processing data, the program will log a message and continue unless the -x option is
specified.

The level of debug messaging is controlled using the -v option, which may be specified up to
4 times:

    -v      log input parameters and file operations
    -vv     log incoming and outgoing messages
    -vvv    log the parsed data of incoming and outgoing messages
    -vvvv   log the raw data of incoming and outgoing messages

Messages logged at the -vv level and above contain the device or file sending or receiving the
message, the direction it was sent, the message size, and a sequence number.  Separate
sequences are kept for incoming and outgoing messages.

The -t option is used to specify the data source type for non-file input.  If the data source is
a serial port, the -t option must be included with either the values 2 or 4 to specify
whether it is connected to the RS232 or RS485 port.  If there is no data source specified and
-t n is specified, semonitor.py will listen on the port specified in the -p option
(or port 22222 if it is not specified) for a connection from an inverter.

To interact directly with an inverter over the network, semonitor.py must function as the SolarEdge
monitoring server.  This means that the host running semonitor.py must be connected to the inverter
over the ethernet interface.  In this configuration, semonitor.py may function as the DHCP server
and the DNS server to provide an IP address to the inverter and to resolve the hostname of the
SolarEdge server (usually prod.solaredge.com) to the IP address of the semonitor.py host.  This
requires that semonitor.py be run with elevated (root) priveleges in order to access the standard
DHCP and DNS ports.  The -n option specifies the name of the network interface that the inverter
is connected to.  If the inverter acquires an IP address and is able to resolve the server hostname
by some other means, the -n option is not required.

The -c, -m, and -s options are not vaild if input is from a file or stdin.

The -m option is only valid if a serial port is specified, and one or more inverter IDs
must be specified with the -s option.  If this option is specified, there cannot
be another master device on the RS485 bus.  semonintor.py will repeatedly send commands to
the specified inverters to request performance data.

The -c option may be specified for a serial device or the network.  The option specifies one
or more SolarEdge protocol command functions separated by a "/".  Each command function
consists of a hex function code followed by zero or more comma separated hex parameters.
Each parameter must begin with one of the letters "B", "H", or "L" to designate the
length of the parameter:

    B = 8 bits
    H = 16 bits
    L = 32 bits

All function codes and parameters must be hexadecimal numbers, without the leading "0x".
Exactly one inverter ID must be specified with the -s option.  After each command is sent,
semonitor.py will wait for a response before sending the next command.  When all commands
have been sent and responded to, the program terminates.  Responses are sent to output.

Commands initiated by semonitor.py as the result of the -c or -m options need to maintain a
monotonically increasing sequence number which is used as a transaction ID.  A file named
seseq.dat will be created to persist the
value of this sequence number across multiple executions of semonitor.py.

#### Examples
    python semonitor.py -o yyyymmdd.json yyyymmdd.dat

Read from SE data file yyyymmdd.dat and write data to the json file yyyymmdd.json.

    python semonitor.py -o yyyymmdd.json -m -s 7f101234,7f105678 -t 4 COM4

Function as a RS485 master to request data from the inverters 7f101234 and 7f105678
using RS485 serial port COM4.

    python semonitor.py -c 0012,H0329 -s 7f101234 -t 2 /dev/ttyUSB0

Send a command to the inverter 7f101234 to request the value of parameter 0x0329
using RS232 serial port /dev/ttyUSB0.  Display the messages on stdout.

    python semonitor.py -c 0011,H329,L0/0030,H01f4,L0 -s 7f101234 -t 2 /dev/ttyUSB0

Send commands to the inverter 7f101234 to set the value of parameter 0x0329 to 0,
followed by a command to reset the inverter using RS232 serial port /dev/ttyUSB0.
Display the debug messages on stdout.

    sudo python semonitor.py -o yyyymmdd.json -n eth1 -k 7f101234.key

Start the dhcp and dns services on network interface eth1.  Accept connections
from inverters and function as a SolarEdge monitoring server.  Use the inverter
encryption key contained in the file 7f101234.key.  Write performance
data to the file yyyymmdd.json.  Because the -n option is specified, the -t n option
is implied.

### seextract.py

This program was intended to extract the TCP stream contining the SolarEdge data
from a PCAP file.  Because it had issues and there exists a number of open source
utilities that perform that function it was removed from the project.

* tshark - https://www.wireshark.org/docs/man-pages/tshark.html
* PcapSplitter - https://github.com/seladb/PcapPlusPlus/tree/master/Examples/PcapSplitter
* tcpflow - https://github.com/simsong/tcpflow
* SplitCap - https://www.netresec.com/?page=SplitCap

### se2state.py
Maintain a JSON file containing the current state of SolarEdge inverters and optimizers.

#### Usage
    python se2state.py options [inFile]

#### Arguments
    inFile          File containing performance data in JSON format. (default:
                    stdin)
                    The program will follow (wait for new data to be written to)
                    the file.

#### Options
    -i inverter[,inverter...] Initialize the state file using the specified inverter
                    IDs rather than using an existing one.  
    -o stateFile    File containing the current (last read) data values for each
                    inverter and optimizer values from the input file.  It will
                    be overwritten every time that new data is read.

#### Examples
    python semonitor.py -t n | tee yyyymmdd.json | python se2state.py -o solar.json

Accept connections from inverters over the network.  Send performance data to
the file yyyymmdd.json and also maintain the file solar.json with the current state.
The inverter acquires its IP address and resolves the server hostname by a means
other than semonitor.py.

### seprint.py
Print a subset of data from a file containing JSON performance data.

#### Usage
    python seprint.py [inFile]

#### Arguments
    inFile          File containing JSON performance data from
                    an inverter output from semonitor.py. (default: stdin)

#### Examples
    python solaredge/seprint.py yyyymmdd.json

### sekey.py
Create a file containing the encryption key for a SolarEdge inverter.

#### Usage
    python sekey.py options [inFile]

#### Arguments
    inFile          File containing the values of the 4 encryption key parameters
                    of an inverter output from semonitor.py. (default: stdin)

#### Options
    -o keyFile      File containing the hex encoded key. (Default: stdout)

#### Examples
    python solaredge/semonitor.py -c 12,H239/12,H23a/12,H23b/12,H23c -s 7f101234 -t 2  /dev/ttyUSB0|python solaredge/sekey.py -o 7f101234.key

Read the parameters 0x0239-0x023c and write the key value to the file 7f101234.key.

### se2csv.py

Convert SolarEdge inverter performance monitoring data from JSON to CSV.

#### Usage
    python se2csv.py options [inFile]

#### Arguments
    inFile          File containing performance data in JSON format. (default:
                    stdin)

#### Options
    -a              append to inverter and optimizer files
    -d delim        csv file delimiter (default: ",")
    -t              write column headers to csv files
    -p csvPrefix    prefix for all csv filenames
    -i invFile      deprecated - use -p instead
    -o optFile      deprecated - use -p instead

#### Examples
    python se2csv.py -p yyyymmdd -t yyyymmdd.json

Read from SE data file yyyymmdd.json and write CSV data  with headers,
for each device type encountered (eg optimizers, inverters, batteries),
to files called yyyymmdd."deviceType".csv

### se2graphite.py

Send SolarEdge performance monitoring data from JSON to a graphite text port.

#### Usage
    python se2graphite.py options [inFile]

#### Arguments
    inFile          File containing performance data in JSON format. (default:
                    stdin)

#### Options
    -b base         base prefix for the names of the metrics sent to graphite
    -h host         the host url or IP address of the graphite server (default: "localhost")
    -p port         the port number of the graphite / carbon text listener port (default: 2003)

#### Examples
    python se2graphite.py -b "semonitor" yyyymmdd.json

Send all numeric metric data for each device encountered in yyymmdd.json
to the graphite server whose "text" port is listening on "localhost:2003".

Metrics are sent one value at a time, with a short delay (default 0.1 sec)
between each transmission.

In graphite / whisper all metric names will begin with "semonitor."


### pickle2graphite.py

Send SolarEdge performance monitoring data from JSON to a graphite pickle listener port.

#### Usage
    python pickle2graphite.py options [inFile]

#### Arguments
    inFile          File containing performance data in JSON format. (default:
                    stdin)

#### Options
    -b base         base prefix for the names of the metrics sent to graphite
    -h host         the host url or IP address of the graphite server (default: "localhost")
    -p port         the port number of the graphite / carbon pickle listener port (default: 2004)
    -f              follow (wait for new data to be written to) the JSON inFile

#### Examples
    python pickle2graphite.py -b "semonitor" yyyymmdd.json

Send all numeric metric data for each device encountered in yyyymmdd.json
to the graphite server whose "pickle" port is listening on "localhost:2004".

Each json line from the file is batched up into a pickled list of metrics,
so many metrics may be sent at the same time. There is a short delay (default 0.2 sec)
between each transmission.

When running "in production" this delay
usually seems to be adequate, but when a large json file with many metrics
which graphite hasn't seen before is sent to graphite, the server may be
swamped, and some metrics may be dropped. Either

* just rerun pickle2graphite.py again, or
* temporarily adjust the delay to say 5.0 secs, or
* even use se2graphite.py once,

any of which should allow the graphite server
enough time to create new whisper files, before the next batch of metrics
from the next line in the json file arrives.

In graphite / whisper all metric names will begin with "semonitor."

If the `-f` option had been included, pickle2graphite.py would follow (wait for new
json lines to be written to) the inFile (yyyymmdd.json) until interrupted
(Ctrl-C) or otherwise killed.
