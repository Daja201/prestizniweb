#!/bin/sh
# backup.sh - daily DB dump + weekly uploads tarball, keeps 7 days of each
set -eu

BACKUP_DIR="/backups"
UPLOAD_SRC="/data/uploads"
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

run_db_backup() {
    stamp="$(date +%Y%m%d-%H%M)"
    out="$BACKUP_DIR/db-$stamp.sql.gz"
    echo "[backup] dumping database to $out"
    pg_dump --no-owner --no-privileges | gzip > "$out.tmp"
    mv "$out.tmp" "$out"
    find "$BACKUP_DIR" -maxdepth 1 -name 'db-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
}

run_uploads_backup() {
    stamp="$(date +%Y%m%d)"
    out="$BACKUP_DIR/uploads-$stamp.tar.gz"
    if [ -d "$UPLOAD_SRC" ]; then
        echo "[backup] archiving uploads to $out"
        tar -czf "$out.tmp" -C "$(dirname "$UPLOAD_SRC")" "$(basename "$UPLOAD_SRC")"
        mv "$out.tmp" "$out"
        find "$BACKUP_DIR" -maxdepth 1 -name 'uploads-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
    fi
}

day_count=0
while true; do
    run_db_backup
    if [ "$((day_count % 7))" -eq 0 ]; then
        run_uploads_backup
    fi
    day_count=$((day_count + 1))
    sleep 86400
done