from __future__ import annotations

import argparse
from pathlib import Path

from backend.net.recovery import cleanup_stale_state, verify_network_configuration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    result = cleanup_stale_state(args.runtime_dir)
    network = verify_network_configuration()
    print("Network Inspector cleanup complete")
    print(f"QUIC rule removed: {result['quic_rule_removed']}")
    print(f"System proxy modified by Inspector: {network['system_proxy_modified']}")


if __name__ == "__main__":
    main()

