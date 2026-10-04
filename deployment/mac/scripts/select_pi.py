#!/usr/bin/env python3
"""Choose a Pi account before opening its settings, credentials or sessions."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def select(args, inherited, interactive, ask=input):
    args = list(args)
    if args and args[0] in ('personal', 'work'):
        return args.pop(0), args
    if inherited in ('personal', 'work'):
        return inherited, args
    if not interactive:
        raise ValueError('Choose an account: pi personal [arguments] or pi work [arguments].')
    answer = ask('Pi account [p]ersonal / [w]ork (Enter cancels): ').strip().lower()
    scope = {'p': 'personal', 'personal': 'personal', 'w': 'work', 'work': 'work'}.get(answer)
    if not scope:
        raise ValueError('No account selected; Pi was not started.')
    return scope, args


def main():
    args = sys.argv[1:]
    if args == ['--help']:
        print('Usage: pi [personal|work] [Pi arguments]\n'
              'Without a scope, inherit AGENT_PROFILE or ask interactively.\n'
              'Direct commands: pi-personal, pi-work.\n'
              'Native help: pi personal --help')
        return
    try:
        scope, args = select(args, os.environ.get('AGENT_PROFILE'), sys.stdin.isatty())
    except (ValueError, EOFError, KeyboardInterrupt) as error:
        sys.exit(str(error) or 'No account selected; Pi was not started.')
    launcher = ROOT / 'launch-harness.py'
    os.execv(sys.executable, [sys.executable, str(launcher), scope, 'pi', *args])


if __name__ == '__main__':
    main()
