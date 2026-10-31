#!/bin/sh

set -eux

export TZ='US/Pacific'

cleanup()
{
	rm -rf "${TMP:-}"
	exit
}

TMP="$(mktemp -d)"
trap cleanup EXIT HUP INT QUIT ABRT ALRM TERM

for rec in test/rec/*.rec; do
	_sample="$(basename "${rec}" ".rec")"
	_output="${TMP}/${_sample}"

	./semonitor.py -v -x -r "${_output}.rec" -o "${_output}.json" "test/rec/${_sample}.rec"
	diff "test/json/${_sample}.json" "${_output}.json"
	cmp "test/rec/${_sample}.rec" "${_output}.rec"

	_tmpse2csv="${_output}.se2csv"
	mkdir "${_tmpse2csv}"
	./conversion/se2csv.py -p "${_tmpse2csv}/${_sample}" -t < "test/json/${_sample}.json"
	diff -w "test/csv/${_sample}/" "${_tmpse2csv}/"

	./semonitor.py -v -x -r "${_output}.re.rec" -o "${_output}.re.json" "test/rec/${_sample}.rec"
	diff "test/json/${_sample}.json" "${_output}.re.json"
	cmp "test/rec/${_sample}.rec" "${_output}.re.rec"
done
