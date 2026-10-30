#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    # Windows consoles default to a legacy code page that cannot print "₵", which made the
    # development console email backend drop notification emails.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
