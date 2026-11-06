#!/bin/bash
# Perbarui server dari GitHub: ambil kode terbaru, bangun ulang API, cek kesehatan.
set -euo pipefail
cd /opt/rms
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "==> Cadangan database (bila skripnya ada)"
if [ -x ./backup.sh ]; then ./backup.sh; fi

echo "==> Ambil kode terbaru"
OLD=$(git rev-parse HEAD)
git fetch origin main
git merge --ff-only origin/main
NEW=$(git rev-parse HEAD)
echo "Versi: $(git rev-parse --short "$OLD") -> $(git rev-parse --short "$NEW")"

echo "==> Bangun dan jalankan ulang"
$COMPOSE up -d --build

echo "==> Tunggu API sehat"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "OK: API sehat (versi $(git rev-parse --short HEAD))"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done

echo "GAGAL: API tidak sehat. Log terakhir:"
$COMPOSE logs api --tail 30
echo
echo "Untuk kembali ke versi sebelumnya:"
echo "  cd /opt/rms && git reset --hard $OLD && $COMPOSE up -d --build"
exit 1