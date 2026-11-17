#!/usr/bin/env bash
# =============================================================
# DMAT 執行期資料備份(Linux / macOS)
# 打包:SQLite 資料庫 + Data Protection 金鑰 + 紀錄單影像 → 單一 .zip
#
# 用法:./scripts/backup-data.sh [輸出資料夾]     (預設 ./backups)
#
# - 資料庫以 SQLite 線上備份 API 複製,服務執行中也能取得一致的快照
#   (直接 cp dmat.db 在 WAL 模式下可能漏掉尚未寫回的交易)。
# - 金鑰(app_data/keys)必須與資料庫一起保存:身分證字號以此金鑰加密,
#   遺失金鑰 = 既有身分證字號永久無法解密。
# - 產出的 zip 含病患個資與解密金鑰,請勿提交至 git、勿放在公開位置。
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DATA="$ROOT/src/Dmat.Web/app_data"
OUT_DIR="${1:-$ROOT/backups}"
ENV_FILE="$ROOT/src/ai-service/.env"

command -v python3 >/dev/null || { echo "找不到 python3" >&2; exit 1; }
[ -f "$APP_DATA/dmat.db" ] || { echo "找不到 $APP_DATA/dmat.db" >&2; exit 1; }
mkdir -p "$OUT_DIR"

python3 - "$APP_DATA" "$OUT_DIR" "$ENV_FILE" <<'PY'
import hashlib, os, platform, sqlite3, sys, tempfile, zipfile
from datetime import datetime
from pathlib import Path

app_data, out_dir, env_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
out = out_dir / f"dmat-backup-{stamp}.zip"

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

with tempfile.TemporaryDirectory() as tmp:
    snap = Path(tmp) / "dmat.db"
    src = sqlite3.connect(f"file:{app_data/'dmat.db'}?mode=ro", uri=True)
    dst = sqlite3.connect(snap)
    src.backup(dst)
    src.close()
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        sys.exit(f"資料庫完整性檢查失敗:{ok}")
    tables = [r[0] for r in dst.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {t: dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    dst.execute("PRAGMA journal_mode=DELETE")  # 快照為單一檔案,還原時不需 -wal/-shm
    dst.close()

    entries = [(snap, "app_data/dmat.db")]
    for p in sorted((app_data / "keys").glob("*.xml")):
        entries.append((p, f"app_data/keys/{p.name}"))
    img_root = app_data / "images"
    n_img = 0
    for p in sorted(img_root.rglob("*")):
        # 略過 0 位元組殘檔、FUSE 暫存檔(.fuse_hidden*)與誤建檔(如 "--raw")
        if not p.is_file() or p.stat().st_size == 0 or p.name.startswith((".", "-")):
            continue
        entries.append((p, f"app_data/images/{p.relative_to(img_root).as_posix()}"))
        n_img += 1
    if env_file.is_file():
        entries.append((env_file, "config/ai-service.env"))

    manifest = [f"DMAT 資料備份  {datetime.now().isoformat(timespec='seconds')}",
                f"來源主機:{platform.node()}", f"資料庫完整性:{ok}",
                f"影像數:{n_img}", "", "== 資料表筆數 =="]
    manifest += [f"{t}\t{c}" for t, c in counts.items()]
    manifest += ["", "== SHA-256 =="]
    manifest += [f"{sha256(p)}  {arc}" for p, arc in entries]

    restore = """DMAT 備份還原方式
================
1. 先停止 DMAT(關掉 start-dev.sh 的終端機,或 Ctrl+C)。
2. 將本壓縮檔內的 app_data/ 解壓到 <專案>/src/Dmat.Web/ 底下,
   覆蓋(或先改名保留)原有的 app_data/。
     Linux  : unzip dmat-backup-XXXX.zip 'app_data/*' -d <專案>/src/Dmat.Web/
     Windows: 解壓後把 app_data 資料夾拖進 <專案>\\src\\Dmat.Web\\
3. config/ai-service.env 是來源主機的 OCR 引擎設定,僅供參考;
   新主機請以 scripts/setup-ocr.sh 重新產生 src/ai-service/.env。
4. 重新啟動 DMAT,登入後抽查傷患明細的影像與身分證字號能否正常顯示。
完整步驟見專案 docs/DMAT轉移部署與重建環境.md。
"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p, arc in entries:
            z.write(p, arc, compress_type=zipfile.ZIP_STORED if arc.endswith(".jpg") else zipfile.ZIP_DEFLATED)
        z.writestr("MANIFEST.txt", "\n".join(manifest) + "\n")
        z.writestr("RESTORE.txt", restore)

with zipfile.ZipFile(out) as z:
    bad = z.testzip()
    if bad:
        sys.exit(f"壓縮檔驗證失敗:{bad}")
os.chmod(out, 0o600)
print(f"[DMAT] 備份完成 → {out}")
print(f"[DMAT] 大小 {out.stat().st_size/1048576:.1f} MB;影像 {n_img} 張;資料表 {len(tables)} 個;完整性 {ok}")
print(f"[DMAT] SHA-256 {sha256(out)}")
print("[DMAT] ⚠ 內含病患個資與解密金鑰,上傳雲端前請加密,並確認儲存位置符合院內規範。")
PY
