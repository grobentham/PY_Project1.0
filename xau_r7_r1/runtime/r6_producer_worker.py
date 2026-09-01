from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .r6_producer_replay import ProducerReplayError, _replay_producer_inprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal isolated worker for trusted R6 producer replay")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--producer-module", type=Path, required=True)
    parser.add_argument("--stream-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        stream, report = _replay_producer_inprocess(args.fixtures, args.producer_module)
        args.stream_output.write_bytes(stream)
        args.report_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except ProducerReplayError as exc:
        print("PRODUCER_WORKER_REPLAY_ERROR:" + str(exc), file=sys.stderr)
        raise SystemExit(20)
    except Exception as exc:
        print("PRODUCER_WORKER_INTERNAL_ERROR:" + exc.__class__.__name__, file=sys.stderr)
        raise SystemExit(21)


if __name__ == "__main__":
    main()
