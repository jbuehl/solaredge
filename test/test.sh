#!/bin/sh

set -eu

export TZ='US/Pacific'

for pcap in `ls test/pcap`
do
    TMP=$(mktemp -d)
    if [ -z "${TMP}" ]; then
        echo "Failed to create temporary directory '${TMP}'"
        break
    fi
    TMPSE2CSV="${TMP}/se2csv"

    SAMPLE="${pcap%.*}"
    KEY_OPTION=""
    if [ -f "test/keys/${SAMPLE}.key" ]
    then
        KEY_OPTION="-k test/keys/${SAMPLE}.key"
    fi
    echo "Running test sample: ${SAMPLE}"
    echo "Key option: ${KEY_OPTION}"
    tshark -r "test/pcap/${SAMPLE}.pcap" -T fields -e data | ./utilities/unhexlify.py | ./semonitor.py -r "${TMP}/${SAMPLE}.rec" -o "${TMP}/${SAMPLE}.json" - $KEY_OPTION
    diff "${TMP}/${SAMPLE}.json" "test/json/${SAMPLE}.json"
    cmp -l "${TMP}/${SAMPLE}.rec" "test/rec/${SAMPLE}.rec"
    mkdir "${TMPSE2CSV}"
    cat "test/json/${SAMPLE}.json" | conversion/se2csv.py -p "${TMPSE2CSV}/${SAMPLE}" -t
    diff "${TMP}/se2csv" "test/csv/${SAMPLE}/" -w

    rm -rf "${TMP}"
done
