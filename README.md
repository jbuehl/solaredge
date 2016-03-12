SolarEdge Monitoring
====================
This project enables monitoring the performance data of SolarEdge inverters and optimizers.
Solaredge supports the open Sunspec Alliance logging protocols, however this data is only 
accessible via an RS485 interface on the inverter and does not include module level (optimizer) 
data.  Solaredge publishes an API that allows access to their portal, however this 
also does not include module level data.

semonitor.py is a program that implements a subset of the SolarEdge protocol.  It can be 
used to parse the performance data that has been previously captured to a file, or it can 
interact directly with a SolarEdge inverter over the RS232, RS485, or ethernet interface.

seextract.py is a program that can extract the SolarEdge protocol messages from a PCAP
file that contains data captured from the network.

See comments in the program sources for more detailed documentation.

