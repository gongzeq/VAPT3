#!/usr/bin/env python3
"""Initialize, seal, and validate an adversarial blackboard run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from blackboard_core import SEVERITIES, STAGES, BlackboardError, init_run, seal_stage, validate_run


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize a run directory")
    init.add_argument("run_dir", type=Path)
    init.add_argument("--question", required=True)
    init.add_argument("--severity", choices=SEVERITIES, default="medium")
    init.add_argument("--revision", required=True)
    init.add_argument("--time-budget-minutes", type=int, default=30)
    init.add_argument("--token-budget", type=int, default=20_000)
    seal = commands.add_parser("seal", help="seal the next ordered stage")
    seal.add_argument("run_dir", type=Path)
    seal.add_argument("stage", choices=STAGES)
    validate = commands.add_parser("validate", help="validate seals and final gates")
    validate.add_argument("run_dir", type=Path)
    commands.add_parser("self-test", help="run dependency-free regression checks")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            init_run(
                args.run_dir,
                args.question,
                args.severity,
                args.revision,
                args.time_budget_minutes,
                args.token_budget,
            )
        elif args.command == "seal":
            seal_stage(args.run_dir, args.stage)
        elif args.command == "validate":
            return 1 if validate_run(args.run_dir) else 0
        else:
            from blackboard_selftest import self_test

            self_test()
    except (BlackboardError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
