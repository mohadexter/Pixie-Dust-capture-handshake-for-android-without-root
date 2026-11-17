"""Bridge a Java log sink to a plain Python callable.

Java objects are not directly callable from Python, so the Android layer hands
us an object with a public ``onLog(String)`` method and we expose a Python
function that forwards to it.
"""


def wrap(sink):
    def _callback(line):
        try:
            sink.onLog(str(line))
        except Exception:  # never let UI logging break the WPS session
            pass

    return _callback
