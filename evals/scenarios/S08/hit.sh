#!/usr/bin/env bash
# Client fixture for eval S08. Sends one request to the server started by server.sh.
set -u
port="$(cat port.txt)"
curl -s -o /dev/null -w 'HTTP-STATUS=%{http_code}\n' "http://127.0.0.1:$port/"
