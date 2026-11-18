Using pairmux, start the background web server `python server.py` in the current directory. It prints
the port it chose (a `PORT=...` line, then a "Serving HTTP" line) and keeps running, logging every HTTP
request it receives.

Once the server is up, use a **second** pairmux terminal to run `python hit.py`, which sends a single
request to that server.

Finally, from the **server** terminal's log, find and report the request line the server recorded for
that hit — it contains the HTTP status code.
