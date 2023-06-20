#!/bin/sh

set -eu
if [ -n "${DEBUG_TRACE_SH:-}" ] && \
   [ "${DEBUG_TRACE_SH:-}" != "${DEBUG_TRACE_SH#*"$(basename "${0}")"*}" ] || \
   [ "${DEBUG_TRACE_SH:-}" = 'all' ]; then
	set -x
fi

se_date_fmt="${SE_DATE_FMT:-%Y%m%d}"
se_start_year="${SE_START_YEAR:-2023}"

# Wait for a reasonable date to be set
while [ "$(date '+%Y')" -lt "${se_start_year}" ]; do
	echo "Date is to far in the past ($(date '+%Y') < ${se_start_year})."
	echo 'Override by setting "SE_START_YEAR" environment variable.'
	sleep 1
done

args="$(echo "${@}" | sed "s|__date__|$(date "+${se_date_fmt}")|g")"

exec '/usr/local/src/semonitor/semonitor.py' ${args:+${args}}

exit 0
