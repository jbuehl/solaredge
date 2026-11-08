#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Copyright (C) 2026 Olliver Schinagl <oliver@schinagl.nl>
#
# Create (or refresh) a local virtualenv with everything needed to run the
# tests, and run them. Nothing is installed outside of ${VENV}.
#
# Usage: ./run-tests.sh                # set up the virtualenv, run all tests
#        ./run-tests.sh -k 'time' -x   # arguments are passed on to pytest
#        .venv/bin/pytest              # run again, without the set up

set -eu

if [ "${DEBUG_TRACE_SH:-}" = 'true' ] || \
   [ "${DEBUG_TRACE_SH:-}" != "${DEBUG_TRACE_SH:+${DEBUG_TRACE_SH#*"$(basename "${0}")"*}}" ]; then
	set -x
fi

VENV="${VENV:-.venv}"

cd "$(dirname "${0}")"

if ! command -v python3 > '/dev/null' 2>&1; then
	echo "python3 is required to create the virtualenv" >&2
	exit 1
fi

echo "Running the tests, which can be run again without the set up below, with:"
echo "  ${VENV}/bin/pytest ${*}"

if ! "${VENV}/bin/python" --version > '/dev/null' 2>&1; then
	python3 -m venv --clear "${VENV}"
fi
"${VENV}/bin/python" -m pip install --quiet --upgrade pip
"${VENV}/bin/python" -m pip install --quiet --upgrade --requirement 'requirements-test.txt'

set -- --cov --cov-report 'term-missing:skip-covered' "${@}"

exec "${VENV}/bin/pytest" "${@}"
