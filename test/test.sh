#!/bin/sh

set -o pipefail
set -eux

export TZ='US/Pacific'

for pcap in $(ls "test/pcap/"); do
    TMP=$(mktemp -d)
    if [ -z "${TMP}" ]; then
        echo "Failed to create temporary directory '${TMP}'"
        break
    fi
    TMPSE2CSV="${TMP}/se2csv"
    SAMPLE="${pcap%.*}"
    REC_OPTION="-r ${TMP}/${SAMPLE}.rec"
    OUT_OPTION="-o ${TMP}/${SAMPLE}.json"
    KEY_OPTION=""
    if [ -f "test/keys/${SAMPLE}.key" ]; then
        KEY_OPTION="-k test/keys/${SAMPLE}.key"
    fi
    SEMONITOR_OPTIONS="${REC_OPTION} ${OUT_OPTION} - ${KEY_OPTION}"

    tshark -r "test/pcap/${SAMPLE}.pcap" -T fields -e data | ./utilities/unhexlify.py | eval ./semonitor.py "${SEMONITOR_OPTIONS}"
    diff "${TMP}/${SAMPLE}.json" "test/json/${SAMPLE}.json"
    cmp -l "${TMP}/${SAMPLE}.rec" "test/rec/${SAMPLE}.rec"
    mkdir "${TMPSE2CSV}"
    ./conversion/se2csv.py -p "${TMPSE2CSV}/${SAMPLE}" -t < "test/json/${SAMPLE}.json"
    diff "${TMPSE2CSV}/" "test/csv/${SAMPLE}/" -w

    if [ -d "${TMP}" ] && [ "${TMP#/tmp/tmp.}x" != "${TMP}x" ]; then
        rm -rf "${TMP}"
    fi
done

exit 0
