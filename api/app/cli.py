import argparse
import getpass
import sys

from app.core.database import SessionLocal
from app.features.users import service as users_service
from app.features.users.roles import Role
from app.core.errors import AppError
from app.core.config import settings
from app.features.attendance import service as attendance_service


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


def purge_photos(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        n = attendance_service.purge_old_photos(db, args.days)
    print(f"{n} catatan absensi dibersihkan dari foto")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user", help="Buat akun (owner pertama, atau akun uji)")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=[r.value for r in Role], default="owner")
    c.add_argument("--outlet-id", default=None)
    c.set_defaults(func=create_user)
    p = sub.add_parser(
        "purge-photos", help="Hapus foto absensi yang melewati masa simpan"
    )
    p.add_argument("--days", type=int, default=settings.photo_retention_days)
    p.set_defaults(func=purge_photos)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
