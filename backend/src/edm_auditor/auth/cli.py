"""CLI utilities for bootstrapping groups and the initial super-admin."""

import argparse
import sys

from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_engine_for, create_session_factory

from .errors import AuthError
from .permissions import ensure_default_groups
from .service import create_super_admin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m edm_auditor.auth.cli",
        description="Bootstrap authentication groups and the initial super-admin user.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override EDM_DATABASE_URL for this command.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed-groups", help="Idempotently seed system and starter custom groups.")

    create_cmd = sub.add_parser(
        "create-super-admin",
        help="Create the single super-admin account.",
    )
    create_cmd.add_argument("--username", required=True)
    create_cmd.add_argument("--email", required=True)
    create_cmd.add_argument("--password", required=True)
    create_cmd.add_argument("--full-name", default="Super Administrator")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = ApiSettings.from_env()
    database_url = args.database_url or settings.database_url
    engine = create_engine_for(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    try:
        if args.command == "seed-groups":
            with session_factory.begin() as session:
                groups = ensure_default_groups(session)
                print(f"Ensured groups: {', '.join(sorted(groups))}")
            return 0

        if args.command == "create-super-admin":
            with session_factory.begin() as session:
                user = create_super_admin(
                    session,
                    username=args.username,
                    email=args.email,
                    password=args.password,
                    full_name=args.full_name,
                )
                print(f"Created super-admin '{user.username}' (id={user.id})")
            return 0
    except AuthError as exc:
        print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
