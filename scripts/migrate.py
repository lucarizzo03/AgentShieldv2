from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentShield Alembic migration runner")
    parser.add_argument(
        "action",
        choices=["upgrade", "downgrade", "revision", "history", "current"],
        help="Migration action",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="head",
        help="Alembic target revision (default: head)",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Revision message (required for revision action)",
    )
    parser.add_argument(
        "--autogenerate",
        action="store_true",
        help="Use Alembic autogenerate with revision action",
    )
    args = parser.parse_args()

    cfg = _alembic_config()
    if args.action == "upgrade":
        command.upgrade(cfg, args.target)
    elif args.action == "downgrade":
        command.downgrade(cfg, args.target)
    elif args.action == "revision":
        if not args.message:
            raise SystemExit("--message is required for revision action")
        command.revision(cfg, message=args.message, autogenerate=args.autogenerate)
    elif args.action == "history":
        command.history(cfg)
    elif args.action == "current":
        command.current(cfg)


if __name__ == "__main__":
    main()

