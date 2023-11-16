#!/usr/bin/env bash

set -o errexit      # make your script exit when a command fails.
set -o nounset      # exit when your script tries to use undeclared variables.

case "$1" in
  wikidata)
    python3 src/main.py --pipeline wikidata
    ;;
  galleries)
    python3 src/main.py --pipeline galleries
    ;;
  deploy)
    python3 src/main.py --pipeline deploy
    ;;
  *)
    exec "$@"
esac