#!/bin/sh

set -eux

export TZ='UTC0'

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

	./semonitor.py -v -x -r "${_output}.re.rec" -o "${_output}.re.json" "test/rec/${_sample}.rec"
	diff "test/json/${_sample}.json" "${_output}.re.json"
	cmp "test/rec/${_sample}.rec" "${_output}.re.rec"
done
