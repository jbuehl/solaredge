#!/usr/bin/env python

# Send JSON performance data to Mosquitto MQTT Broker
#
# -c mosquitto client id
# -u mosquitto client user id
# -p mosquitto client password
# -s mosquitto server (dns or ip address)
# -t mosquitto MQTT topic to publish to
#
#example:
#
# python2 se2MQTT.py -c solaredge -u solaredge -p s0lar3dg3 -s mosquitto.domain.local -t /ha/value/solaredge /root/solaredge/performance.json
#
# follow /root/solaredge/performance.json file and publish to topic "/ha/value/solaredge" on server "mosquitto.domain.local" with client id "solaredge" and user "solaredge" and password "s0lar3dg3"
#
# python2 semonitor.py -t 4 -d /root/solaredge/selog.txt -s 7f123456 -vvvv /dev/ttyUSB0 | python2 se2MQTT.py -c solaredge -u solaredge -p s0lar3dg3 -s mosquitto.domain.local -t /ha/value/solaredge
#
# pipe output from semonitor directly into se2MQTT.py and publish to topic "/ha/value/solaredge" on server "mosquitto.domain.local" with client id "solaredge" and user "solaredge" and password "s0lar3dg3"

import json
import getopt
import time
import sys
import paho.mqtt.client as mqtt

# state values
stateDict = {"inverters": {}, "optimizers": {}}

# get program arguments and options
(opts, args) = getopt.getopt(sys.argv[1:], "c:u:p:s:t:")
try:
    inFile = open(args[0])
except:
    inFile = sys.stdin
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
while True:
    jsonStr = ""
    # wait for data
    while jsonStr == "":
        time.sleep(.1)
        jsonStr = inFile.readline()
    inDict = json.loads(jsonStr)
    # update the state values
    stateDict["inverters"].update(inDict["inverters"])
    stateDict["optimizers"].update(inDict["optimizers"])
    # zero current energy and power when an event occurs
    if len(inDict["events"]) != 0:
        for inverter in stateDict["inverters"].keys():
            stateDict["inverters"][inverter]["Eac"] = 0.0
            stateDict["inverters"][inverter]["Pac"] = 0.0
    # send to MQTT
    try:
        mqttc = mqtt.Client(client_id=clientid)
        mqttc.username_pw_set(user, passwd)
        mqttc.connect(server)
        mqttc.publish(topic, json.dumps(stateDict))
        mqttc.disconnect()
    except Exception as ex:
        print "MQTT Exception: " + str(ex)
