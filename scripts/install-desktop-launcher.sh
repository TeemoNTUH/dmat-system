#!/usr/bin/env bash
# =============================================================
# 依專案在本機的實際位置,產生 DMAT 桌面啟動器(Linux / GNOME 等)
#
# 用法:./scripts/install-desktop-launcher.sh [目標資料夾 ...]
#   未指定時安裝到「桌面」與應用程式選單
#   (~/.local/share/applications,可在活動總覽搜尋「DMAT」)。
#
# repo 內只保存範本 scripts/start-dmat.desktop.in,不含任何本機路徑,
# 避免帳號名稱與目錄結構隨程式碼公開;換機或搬移專案後重新執行一次即可。
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/scripts/start-dmat.desktop.in"
NAME="start-dmat.desktop"

[ -f "$TEMPLATE" ] || { echo "找不到範本 $TEMPLATE" >&2; exit 1; }

# .desktop 的 Exec 欄位對 " ` $ \ 有特殊跳脫規則,含這些字元的路徑一律拒絕
case "$ROOT" in
  *[\"\`\$\\]*) echo "專案路徑含有 \" \` \$ \\ 等字元,桌面啟動器無法正確引用:$ROOT" >&2
                echo "請把專案搬到不含這些字元的路徑後再執行。" >&2; exit 1 ;;
esac

if [ "$#" -gt 0 ]; then
  TARGETS=("$@")
else
  DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  # xdg-user-dir 找不到設定時會回傳 $HOME 本身,不可把啟動器丟進家目錄
  if [ -z "$DESKTOP_DIR" ] || [ "$DESKTOP_DIR" = "$HOME" ]; then DESKTOP_DIR="$HOME/Desktop"; fi
  TARGETS=("$DESKTOP_DIR" "${XDG_DATA_HOME:-$HOME/.local/share}/applications")
fi

TEMPLATE_TEXT="$(<"$TEMPLATE")"
# 替換字串加引號:bash 5.2 起 & 在替換字串中有特殊意義,引號可停用
CONTENT="${TEMPLATE_TEXT//@DMAT_ROOT@/"$ROOT"}"
# 移除範本專用的註解(產生後的檔案不需要「請勿提交」提示)
CONTENT="$(printf '%s\n' "$CONTENT" | grep -v '^#')"

for dir in "${TARGETS[@]}"; do
  mkdir -p "$dir"
  dest="$dir/$NAME"
  tmp="$(mktemp "$dir/.${NAME}.XXXXXX")"
  printf '%s\n' "$CONTENT" > "$tmp"
  chmod 755 "$tmp"
  mv -f "$tmp" "$dest"   # 若原本是指向舊路徑的符號連結,會直接以新檔取代
  # GNOME 桌面需標記為受信任才可直接點擊啟動;其他桌面環境沒有此屬性,失敗可忽略
  command -v gio >/dev/null 2>&1 && gio set "$dest" metadata::trusted true 2>/dev/null || true
  echo "[DMAT] 已安裝啟動器 → $dest"
done

command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$dest" || true
echo "[DMAT] 專案路徑:$ROOT"
echo "[DMAT] 若桌面圖示顯示「不受信任的啟動器」,請右鍵 →「允許啟動」。"
