#!/bin/bash -e

export TZ='US/Pacific'

for pcap in `ls test/pcap`
do
    TMP=$(mktemp -d)
    if [ -z "${TMP}" ]; then
        echo "Failed to create temporary directory '${TMP}'"
        break
    fi

    SAMPLE="${pcap%.*}"
    KEY_OPTION=""
    if [ -f test/keys/$SAMPLE.key ]
    then
        KEY_OPTION="-k test/keys/$SAMPLE.key"
    fi
    echo Running test sample: $SAMPLE
    echo Key option: $KEY_OPTION
    diff <(tshark -r test/pcap/$SAMPLE.pcap -T fields -e data | ./utilities/unhexlify.py | ./semonitor.py - $KEY_OPTION) test/json/$SAMPLE.json
    cat test/json/$SAMPLE.json | conversion/se2csv.py -p $TMP/$SAMPLE -t
    diff $TMP/ test/csv/$SAMPLE/ -w

    rm -rf "${TMP}"
done
