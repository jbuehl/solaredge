#!/bin/bash -e

export TZ='US/Pacific'

TMP=/tmp/outputs

for pcap in `ls test/pcap`
do
    rm -rf $TMP
    mkdir $TMP

    SAMPLE="${pcap%.*}"
    KEY_OPTION=""
    if [ -f test/keys/$SAMPLE.key ]
    then
        KEY_OPTION="-k test/keys/$SAMPLE.key"
    fi
    echo Running test sample: $SAMPLE
    echo Key option: $KEY_OPTION
    diff <(tshark -r test/pcap/$SAMPLE.pcap -T fields -e data | ./utilities/unhexlify.py | ./semonitor.py - $KEY_OPTION) test/json/$SAMPLE.json
    cat test/json/$SAMPLE.json | PYTHONPATH=./ conversion/se2csv.py -p $TMP/$SAMPLE -h
    diff $TMP/ test/csv/$SAMPLE/
done
