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
	_output="${TMP}/output/${_sample}"

	./semonitor.py -v -x -r "${_output}.rec" -o "${_output}.json" "test/rec/${_sample}.rec"
	diff "test/json/${_sample}.json" "${_output}.json"
	cmp "test/rec/${_sample}.rec" "${_output}.rec"

	./semonitor.py -v -x -r "${_output}.rec" -o "${_output}.json" "test/rec/${_sample}.rec"
	diff "test/json/${_sample}.json" "${_output}.1.json"
	cmp "test/rec/${_sample}.rec" "${_output}.1.rec"

	./semonitor.py -a -v -x -r "${_output}.rec" -o "${_output}.json" "test/rec/${_sample}.rec"
	cat "test/json/${_sample}.json" "test/json/${_sample}.json" | \
	cmp - "${_output}.json"
	cat "test/rec/${_sample}.rec" "test/rec/${_sample}.rec" | \
	cmp - "${_output}.rec"
	test ! -e "${_output}.2.json"
	test ! -e "${_output}.2.rec"
done
