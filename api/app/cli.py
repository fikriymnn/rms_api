import argparse
import getpass
import sys

from app.core.database import SessionLocal
from app.features.users import service as users_service
from app.features.users.roles import Role
from app.core.errors import AppError


def create_user(args: argparse.Namespace) -> None:
    password = getpass.getpass("Password (min. 8 karakter): ")
    if len(password) < 8:
        sys.exit("Password minimal 8 karakter")
    if password != getpass.getpass("Ulangi password: "):
        sys.exit("Password tidak sama")
    with SessionLocal() as db:
        try:
            user = users_service.create_user(
                db,
                username=args.username,
                password=password,
                name=args.name,
                role=Role(args.role),
                outlet_id=args.outlet_id,
            )
        except AppError as e:
            sys.exit(e.detail)
        print(f"Akun dibuat: {user.username} ({user.role}) id={user.id}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user", help="Buat akun (owner pertama, atau akun uji)")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=[r.value for r in Role], default="owner")
    c.add_argument("--outlet-id", default=None)
    c.set_defaults(func=create_user)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
