SolarEdge Monitoring
====================
This project is for directly monitoring the output of SolarEdge inverters by capturing
the network traffic between the inverters and the SolarEdge server.  This approach was
chosen in order to be able to access module level data and to reduce dependencies on 
Solaredge.

Solaredge supports the Sunspec Alliance logging protocols, however this data is only 
accessible via an RS485 interface on the inverter and does not include module level 
data.  Solaredge also publishes an API that allows access to their portal, however this 
also does not include module level data.

Hardware
--------
I have two SE5000 inverters with 34 solar panels.  The inverters are connected together
using RS485 with one configured as the master and the other as the slave.  The master is
connected to the internet via hardwired ethernet.

A Raspberry Pi model B running Arch linux is used as an ethernet bridge through which
all traffic to and from the inverters must flow.  A second ethernet port on the RPi is
enabled with a USB ethernet dongle.  The cable from the inverters is plugged directly
into one port and the other port is connected to the network.

Configuration
-------------
The only configuration required is for the network bridge interface by placing the config 
file br0 in /etc/netctl/.  The operating system will then automatically pass all traffic
between the two ethernet interfaces, eth0 and eth1.

Software
--------
There are two services that are enabled, secapture and seconvert.  These services are
restarted every day at midnight by a cron job.

secapture uses the tcpdump utility to capture network traffic between the inverters and
the SolarEdge server into a pcap file.  The file is named based on its creation time.

seconvert reads the SolarEdge logging data in a pcap file and converts it.  The output
is sent to one or more destinations:

- log entries in a database
- log entries in flat files
- a file containing the current values formatted as json

