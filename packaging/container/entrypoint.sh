#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Copyright (C) 2023 Olliver Schinagl <oliver@schinagl.nl>
#
# A new user should be able to docker run image bash (or sh) without
# needing to learn about --entrypoint
# https://github.com/docker-library/official-images#consistency

set -eu

if [ "${DEBUG_TRACE_SH:-}" = 'true' ] || \
   [ "${DEBUG_TRACE_SH:-}" != "${DEBUG_TRACE_SH:+${DEBUG_TRACE_SH#*"$(basename "${0}")"*}}" ]; then
	set -x
fi

bin='/usr/local/bin/semonitor'

# Run command, unless it is an option, directory, device or data file
if [ "${#}" -gt 0 ] && \
   [ "${1#-}" = "${1}" ] && \
   [ ! -d "${1}" ] && \
   [ ! -b "${1}" ] && \
   [ ! -c "${1}" ] && \
   { [ ! -f "${1}" ] || [ -x "${1}" ]; } && \
   command -v "${1}" > '/dev/null' 2>&1; then
	exec "${@}"
fi


exec "${bin}" "${@}"

exit 0
