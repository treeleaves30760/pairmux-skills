#!/usr/bin/env bash
# Confirmation-prompt fixture for eval S04.
set -u
printf 'Delete all temporary files? [y/N] '
read -r ans
case "$ans" in
  y|Y|yes|YES) echo "CONFIRMED-DELETING" ;;
  *)           echo "ABORTED" ;;
esac
