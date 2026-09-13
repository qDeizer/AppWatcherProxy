from __future__ import annotations

import argparse
import time
from pathlib import Path

import psutil

from backend.net.recovery import cleanup_stale_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    while True:
        if not psutil.pid_exists(args.parent_pid):
            cleanup_stale_state(args.runtime_dir)
            return
        try:
            parent = psutil.Process(args.parent_pid)
            if parent.status() == psutil.STATUS_ZOMBIE:
                cleanup_stale_state(args.runtime_dir)
                return
        except psutil.Error:
            cleanup_stale_state(args.runtime_dir)
            return
        time.sleep(1)


if __name__ == "__main__":
    main()

