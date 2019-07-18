#!/usr/bin/env bash

set -o pipefail
set -eux

export TZ='US/Pacific'

for pcap in test/pcap/*.pcap; do
    TMP=$(mktemp -d)
    if [ ! -d "${TMP}" ]; then
        echo "Failed to create temporary directory '${TMP}'"
        break
    fi
    TMPSE2CSV="${TMP}/se2csv"
    SAMPLE="$(basename -s ".pcap" "${pcap}")"
    REC_OPTION="-r ${TMP}/${SAMPLE}.rec"
    OUT_OPTION="-o ${TMP}/${SAMPLE}.json"
    KEY_OPTION=""
    if [ -f "test/keys/${SAMPLE}.key" ]; then
        KEY_OPTION="-k test/keys/${SAMPLE}.key"
    fi
    SEMONITOR_OPTIONS="${REC_OPTION} ${OUT_OPTION} - ${KEY_OPTION} -v -x"

    tshark -r "test/pcap/${SAMPLE}.pcap" -T fields -e data | xxd -r -p | ./semonitor.py ${SEMONITOR_OPTIONS}
    diff "test/json/${SAMPLE}.json" "${TMP}/${SAMPLE}.json"
    cmp -l "test/rec/${SAMPLE}.rec" "${TMP}/${SAMPLE}.rec"
    mkdir "${TMPSE2CSV}"
    ./conversion/se2csv.py -p "${TMPSE2CSV}/${SAMPLE}" -t < "test/json/${SAMPLE}.json"
    diff "test/csv/${SAMPLE}/" "${TMPSE2CSV}/" -w

    IN_OPTION="test/rec/${SAMPLE}.rec"
    REC_OPTION="-r ${TMP}/${SAMPLE}.re.rec"
    OUT_OPTION="-o ${TMP}/${SAMPLE}.re.json"
    SEMONITOR_OPTIONS="${REC_OPTION} ${OUT_OPTION} ${IN_OPTION} ${KEY_OPTION} -v -x"
    ./semonitor.py ${SEMONITOR_OPTIONS}
    diff "test/json/${SAMPLE}.json" "${TMP}/${SAMPLE}.re.json"
    cmp -l "test/rec/${SAMPLE}.rec" "${TMP}/${SAMPLE}.re.rec"

    if [ -d "${TMP}" ] && [ "${TMP#/tmp/tmp.}x" != "${TMP}x" ]; then
        rm -rf "${TMP}"
    fi
done
