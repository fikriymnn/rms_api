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


def push_test(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from app.features.notifications import fcm
    from app.features.notifications.models import DeviceToken

    if not fcm.is_configured():
        sys.exit(
            "FCM belum dikonfigurasi (FCM_SERVICE_ACCOUNT_FILE tidak ada atau berkas tidak ditemukan)"
        )
    with SessionLocal() as db:
        user = users_service.get_by_username(db, args.username)
        if user is None:
            sys.exit("Akun tidak ditemukan")
        tokens = [
            t.token
            for t in db.scalars(
                select(DeviceToken).where(DeviceToken.user_id == user.id)
            )
        ]
    if not tokens:
        sys.exit("Akun ini belum punya perangkat terdaftar. Login di aplikasi dulu.")
    for t in tokens:
        result = fcm.send(
            {
                "token": t,
                "title": "Tes notifikasi",
                "body": "FCM berfungsi.",
                "channel": args.channel,
                "data": {"type": "test", "id": ""},
            }
        )
        print(f"{t[:12]}… -> {result}")


def revoke_consent(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        user = users_service.get_by_username(db, args.username)
        if user is None:
            sys.exit("Akun tidak ditemukan")
        out = attendance_service.revoke_consent(db, user)
    print(f"Persetujuan dicabut. {out.photos_deleted} foto dihapus.")


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
    t = sub.add_parser(
        "push-test", help="Kirim notifikasi uji ke perangkat sebuah akun"
    )
    t.add_argument("--username", required=True)
    t.add_argument(
        "--channel", default="approvals", choices=["approvals", "kitchen_orders"]
    )
    t.set_defaults(func=push_test)
    rc = sub.add_parser(
        "revoke-consent",
        help="Cabut persetujuan absensi sebuah akun dan hapus foto wajahnya",
    )
    rc.add_argument("--username", required=True)
    rc.set_defaults(func=revoke_consent)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
