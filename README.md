SolarEdge Monitoring
====================
This project enables monitoring the performance data of SolarEdge inverters and optimizers.
Solaredge supports the open Sunspec Alliance logging protocols, however this data is only 
accessible via an RS485 interface on the inverter and does not include module level (optimizer) 
data.  Solaredge publishes an API that allows access to their portal, however this 
also does not include module level data.

**semonitor.py** is a program that implements a subset of the SolarEdge protocol.  It can be 
used to parse the performance data that has been previously captured to a file, or it can 
interact directly with a SolarEdge inverter over the RS232, RS485, or ethernet interface.
Performance data is output to a file in JSON format.

**seextract.py** is a program that can extract the SolarEdge protocol messages from a PCAP
file that contains data captured from the network.

**se2state.py** follows a file containing performance data and outputs a JSON file
that contains the current state of the inverter and optimizer values.

**se2csv.py** reads a file containing performance data and outputs two separate comma delimited
files that contain inverter and optimizer data that is suitable for input to a spreadsheet.

semonitor.py
------------

SolarEdge inverter performance monitoring using the SolarEdge protocol.

### Usage: 
    python semonitor.py [options] [datasource]

### Arguments:
    datasource           Input filename or serial port.
                         If no data source is specified, the program reads from 
                         stdin, unless the data source type is network.
                         If a file name is specified, the program processes the 
                         data in that file and terminates, unless the -f option 
                         is specified, in which case it waits for further data 
                         to be written to the file.
                         If the data source corresponds to a serial port, 
                         process the data from that port.

### Options:
    -a                   append to output file if the file exists
    -b                   baud rate for serial data source (default: 115200)
    -c cmd[/cmd/...]     send the specified command functions
    -d debugfile         where to send debug messages (stdout|syslog|filename) 
                         (default: syslog)
    -f                   wait for appended data as the input file grows 
                         (as in tail -f)
    -l logfile           file to write all incoming and outgoing messages to
    -m                   function as a RS485 master
    -n interface         run DHCP and DNS network services on the specified 
                         interface
    -o outfile           write performance logging the the specified file in 
                         JSON format (default: stdout)
    -s inv[,inv,...]     comma delimited list of SolarEdge slave inverter IDs
    -t 2|4|n             data source type (2=RS232, 4=RS485, n=network)
    -v                   verbose output
    -x                   halt on data exception

### Notes:
Data may be read from a file containing messages in the SolarEdge protocol that was previously created by 
seextract from a pcap file, or the output from a previous run of semonitor.  It may also be
read in real time from one of the RS232, RS485, or ethernet interfaces on a SolarEdge inverter.

Messages are sent to the system log, unless the -d option is specified.  If an error occurs
while processing data, the program will log a message and continue unless the -x option is
specified.

The level of debug messaging is controlled using the -v option, which may be specified up to
4 times:
    -v      log input parameters and file operations
    -vv     log incoming and outgoing messages
    -vvv    log the parsed data of incoming and outgoing messages
    -vvvv   log the raw data of incoming and outgoing messages
Messages logged at the -vv level and above contain the device or file sending or receiving the
message, the direction it was sent, the message size, and an internal sequence number.  Separate
sequences are kept for incoming and outgoing messages.

data source type

To interact directly with an inverter over the network, semonitor must function as the SolarEdge
monitoring server.  This means that the host running semonitor must be connected to the inverter
over a dedicated ethernet connection.  In this configuration, semonitor may function as the DHCP server
and the DNS server to provide an IP address to the inverter and to resolve the hostname of the
SolarEdge server (usually prod.solaredge.com) to the IP address of the semonitor host.  This
requires that semonitor be run with elevated (root) priveleges in order to access the standard
DHCP and DNS ports.  The -n option specifies the name of the network interface that the inverter
is connected to.

The -c, -m, and -s options are not meaningful if input is from a file or stdin.

The -m option is only valid if a serial port is specified, and one or more inverter IDs
must be specified with the -s option.  If this option is specified, there cannot
be another master device on the RS485 bus.  semonintor will repeatedly send commands to
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
semonitor will wait for a response before sending the next command.  When all commands
have been sent and responded to, the program terminates.  Use the -vvv option to view
the responses.

seseq.dat

### Examples:
    python semonitor.py -o yyyymmdd.json yyyymmdd.se

Read from the file yyyymmdd.se and write data to the json file yyyymmdd.json.

    python semonitor.py yyyymmdd.se | python json2csv.py -i yyyymmdd.inv -o yyyymmdd.opt -H

Read from the file yyyymmdd.se and write inverter and optimizer data to the csv files
yyyymmdd.inv and yyyymmdd.opt with headers.

    python seextract.py yyyymmdd.pcap | python semonitor.py -o yyyymmdd.json

Extract SolarEdge data from the file yyyymmdd.pcap using seextract, process
it with semonitor, and write data to the json file yyyymmdd.json.

    python semonitor.py -j yyyymmdd.json -m -s RS232 7f101234,7f105678 -t 4 COM4

Function as a RS485 master to request data from the inverters 7f101234 and 7f105678
using serial port COM4.

    python semonitor.py -c 0012,H0329 -s 7f101234 -d stdout -vvv -t 2 /dev/ttyUSB0

Send a command to the inverter 7f101234 to request the value of parameter 0x0329
using serial port /dev/ttyUSB0.  Display the messages on stdout.

    python semonitor.py -c 0011,H329,L1/0012,H329/0030,H01f4,L0 -s 7f101234 -d stdout -vvv -t 2 /dev/ttyUSB0

Send commands to the inverter 7f101234 to set the value of parameter 0x0329 to 1,
followed by a command to reset the inverter using RS232 serial port /dev/ttyUSB0.
Display the messages on stdout.

    sudo python semonitor.py -o yyyymmdd.json -t n -n eth1

Start the dhcp and dns services on network interface eth1.  Accept connections
from inverters and function as a SolarEdge monitoring server.  Write performance
data to file yyyymmdd.json.

seextract.py
------------

Read a PCAP file that is a capture of the traffic between a inverter and the SolarEdge 
monitoring server.  Filter out the TCP stream between the inverter to the server.

### Usage: 
    python seextract.py [options] pcapFile
    
### Arguments:
    pcapFile        pcap file or directory to read
                    If a file is specified, the program processes the data in 
                    that file and terminates, unless the -f option is specified, 
                    in which case it waits for further data to be written to the 
                    pcap file.
                    If a directory is specified, all files in the directory are 
                    processed.
                    If a directory is specified and the -f option is specified, 
                    only the file in the directory with the newest modified date 
                    is processed and the program waits for further data in that 
                    file.  If a new file is subsequently created in the 
                    directory, the current file is closed and the new file 
                    is opened. 
### Options:
    -a              append to output files
    -f              output appended data as the pcap file grows (as in tail -f)
    -o outfile      output file to write
    -s server       SolarEdge server hostname or IP address (default: 
                    prod.solaredge.com)
    -v              verbose output

### Examples:
    python seextract.py -o test.pcap pcap-20140122000001.pcap

Convert the data in file pcap-20140122000001.pcap and write the output to file
test.pcap
    
    python seextract.py -f pcap/

Monitor PCAP files in directory pcap/ and write the current values to stdin.
    
    python seextract.py -o allfiles.pcap pcap/

Convert all the pcap files found in directory pcap/ and write the output to files
allfiles.pcap.

se2state.py
-----------
### Usage
### Arguments
### Options
### Examples

se2csv.py
---------
### Usage
### Arguments
### Options
### Examples


