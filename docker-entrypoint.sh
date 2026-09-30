#!/bin/sh
# Make the data volume writable by the app user, then run the app as that user.
set -e
mkdir -p /data
chown -R mx:mx /data
exec setpriv --reuid=mx --regid=mx --init-groups "$@"
