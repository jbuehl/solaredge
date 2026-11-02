#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Copyright (C) 2026 Olliver Schinagl <oliver@schinagl.nl>
#
# Create (or refresh) a local virtualenv with pre-commit, install the git
# hook, and run all checks. Nothing is installed outside of ${VENV} (apart
# from pre-commit's own hook-environment cache in ~/.cache/pre-commit).
#
# Usage: ./pre-commit.sh
#            Set up the virtualenv and check all files.
#        ./pre-commit.sh --files foo.py
#            Arguments are passed on to 'pre-commit run'.
#        ./pre-commit.sh cspell --all-files
#            Run a single check, by its id.
#        ./pre-commit.sh --hook-stage manual codespell-fix
#            Run a check that is only run on request.
#        .venv/bin/pre-commit run --all-files
#            Run again, without the set up.

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

echo "Running pre-commit, which can be run again, without the set up, with:"
echo "  ${VENV}/bin/pre-commit run ${*}"

if ! "${VENV}/bin/python" --version > '/dev/null' 2>&1; then
	python3 -m venv --clear "${VENV}"
fi
"${VENV}/bin/python" -m pip install --quiet --upgrade pip
"${VENV}/bin/python" -m pip install --quiet --upgrade --group 'dev'

"${VENV}/bin/pre-commit" clean
"${VENV}/bin/pre-commit" install --install-hooks

if [ "${#}" -eq 0 ]; then
	set -- --all-files
fi

exec "${VENV}/bin/pre-commit" run "${@}"
