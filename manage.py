#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def add_default_runserver_address(argv):
    """Use the SZLG+ development port unless runserver receives an address."""
    if len(argv) < 2 or argv[1] != "runserver":
        return argv

    value_options = {"--settings", "-s", "--pythonpath", "-p", "--verbosity", "-v"}
    positional = False
    skip_value = False
    for argument in argv[2:]:
        if skip_value:
            skip_value = False
            continue
        if argument in value_options:
            skip_value = True
            continue
        if argument.startswith("-"):
            continue
        positional = True
        break

    if not positional:
        return [*argv, "127.0.0.1:8002"]
    return argv


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "szlg_plusz.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(add_default_runserver_address(sys.argv))


if __name__ == '__main__':
    main()
