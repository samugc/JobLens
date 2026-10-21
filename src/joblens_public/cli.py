"""Command-line entry point for the public demo."""
from __future__ import annotations

import argparse
import webbrowser
from typing import Sequence

from .data import load_demo_data
from .webapp import create_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local, synthetic JobLens public demo"
    )
    parser.add_argument("--port", type=int, default=0,
                        help="Loopback port; 0 chooses a free port")
    parser.add_argument("--open", action="store_true",
                        help="Open the demo in the default browser")
    args = parser.parse_args(argv)

    candidates, jobs = load_demo_data()
    with create_server(candidates, jobs, args.port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print("JobLens public demo", flush=True)
        print(f"  URL: {url}", flush=True)
        print(f"  Fictional candidates: {len(candidates)}", flush=True)
        print(f"  Synthetic postings: {len(jobs)}", flush=True)
        print("  Evaluator: Python (local only, no upload, no persistence)", flush=True)
        print("  Stop with Ctrl+C", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0
