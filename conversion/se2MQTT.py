#!/usr/bin/env python3
r"""
Send JSON performance data to Mosquitto MQTT broker.

Options:
    -c Mosquitto client ID
    -u Mosquitto client user ID
    -p Mosquitto client password
    -s Mosquitto server (DNS or IP address)
    -t Mosquitto MQTT topic to publish to

Example:
    Follow /root/solaredge/performance.json and publish to topic
    "/ha/value/solaredge" on server "mosquitto.domain.local" with client ID
    "solaredge" and user "solaredge" and password "s0lar3dg3"::

        python3 se2MQTT.py -c solaredge -u solaredge -p s0lar3dg3 \\
            -s mosquitto.domain.local -t /ha/value/solaredge \\
            /root/solaredge/performance.json

    Or pipe the output of semonitor directly into se2MQTT.py::

        python3 semonitor.py -t 4 -d /root/solaredge/selog.txt -s 7f123456 -vvvv \\
            /dev/ttyUSB0 | \\
            python3 se2MQTT.py -c solaredge -u solaredge -p s0lar3dg3 \\
            -s mosquitto.domain.local -t /ha/value/solaredge
"""

import getopt
import json
import sys
import time

import paho.mqtt.client as mqtt
from common import open_input

# state values
state_dict = {"inverters": {}, "optimizers": {}}

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "c:u:p:s:t:")
in_file = open_input(args)
for opt in opts:
    if opt[0] == "-c":
        clientid = opt[1]
    if opt[0] == "-u":
        user = opt[1]
    if opt[0] == "-p":
        passwd = opt[1]
    if opt[0] == "-s":
        server = opt[1]
    if opt[0] == "-t":
        topic = opt[1]

# read the input forever
with in_file:
    while True:
        json_str = ""
        # wait for data
        while json_str == "":
            time.sleep(0.1)
            json_str = in_file.readline()
        in_dict = json.loads(json_str)
        # update the state values
        state_dict["inverters"].update(in_dict["inverters"])
        state_dict["optimizers"].update(in_dict["optimizers"])
        # zero current energy and power when an event occurs
        if len(in_dict["events"]) != 0:
            for inverter in state_dict["inverters"]:
                state_dict["inverters"][inverter]["Eac"] = 0.0
                state_dict["inverters"][inverter]["Pac"] = 0.0
        # send to MQTT
        try:
            mqttc = mqtt.Client(client_id=clientid)
            mqttc.username_pw_set(user, passwd)
            mqttc.connect(server)
            mqttc.publish(topic, json.dumps(state_dict))
            mqttc.disconnect()
        except (OSError, ValueError) as ex:
            sys.stderr.write(f"MQTT Exception: {ex}\n")
