#!/usr/bin/env python3
"""Launch the native ACP agent with Debian's name for the nobody group."""
import grp
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: launch_antigravity.py /absolute/path/to/agy_acp_server.par [arguments]')
    binary = Path(sys.argv[1])
    if not binary.is_absolute() or not os.access(binary, os.X_OK):
        sys.exit('Supply an installed native Antigravity ACP executable')
    arguments = sys.argv[2:]
    if sys.platform == 'linux' and not any(arg == '--gid' or arg.startswith('--gid=') for arg in arguments):
        try:
            grp.getgrnam('nobody')
        except KeyError:
            grp.getgrnam('nogroup')
            arguments = ['--gid=nogroup', *arguments]
    os.execv(str(binary), [str(binary), *arguments])


if __name__ == '__main__':
    main()
