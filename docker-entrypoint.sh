#!/usr/bin/env bash

set -o errexit      # make your script exit when a command fails.
set -o nounset      # exit when your script tries to use undeclared variables.

case "$1" in
  wikidata)
    python3 src/main.py --pipeline wikidata
    ;;
  galleriesnow)
    python3 src/main.py --pipeline galleriesnow
    ;;
  *)
    exec "$@"
esac