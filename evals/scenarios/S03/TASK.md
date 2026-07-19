The file `haystack.log` in the current directory has about ten thousand lines. Exactly one of them
reports a FATAL error, and that line includes an error code.

First use pairmux to send every line of the file to a terminal's output. Do not filter, search, or
pre-read the source file: the initial pairmux response should be forced to truncate the large output.
Then, without redisplaying the file or reading the source again, query that terminal's persisted
pairmux journal to find the single FATAL line. Report it verbatim — including its error code.
