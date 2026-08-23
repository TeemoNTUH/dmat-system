#!/usr/bin/env bash
# =============================================================
# DMAT 開發環境快速啟動腳本 (Linux / macOS)
# 一次啟動：AI 辨識服務 (FastAPI :8100) + Web 應用 (.NET :5100)
# 用法：./start-dev.sh   （按 Ctrl+C 可同時關閉兩個服務）
#
# 啟動順序：Web 應用一律優先啟動、優先開瀏覽器；
# AI 服務相關的一切（Python 環境安裝、推論容器喚醒、模型載入）
# 全部丟到背景慢慢跑，不會卡住網站上線。
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$ROOT/src/ai-service"
WEB_DIR="$ROOT/src/Dmat.Web"
VENV="$AI_DIR/.venv"

info(){ printf '\033[1;34m[DMAT]\033[0m %s\n' "$1"; }
warn(){ printf '\033[1;33m[DMAT]\033[0m %s\n' "$1"; }
err(){  printf '\033[1;31m[DMAT]\033[0m %s\n' "$1" >&2; }
ai_info(){ printf '\033[1;36m[DMAT/AI]\033[0m %s\n' "$1"; }
ai_warn(){ printf '\033[1;33m[DMAT/AI]\033[0m %s\n' "$1"; }

# --noproxy:推論端點在本機,不可走公司代理設定
infer_up(){ curl -s -o /dev/null --noproxy '*' --max-time 3 "$1/v1/models"; }

# 使用真實引擎時,確認推論伺服器活著;容器只是停著就把它叫起來。
# 現場沒有人會記得「先開推論伺服器」,漏開的症狀又是整批照片默默降級為人工輸入。
# 這一段本身可能要等上好幾分鐘(模型載入),因此只會在背景執行,不擋網站启動。
ensure_inference(){
  [ "$ENGINE" = "mock" ] && return 0

  local base
  base="$(sed -n 's/^DMAT_VISION_BASE_URL=//p' "$AI_DIR/.env" 2>/dev/null | tail -1)"
  base="${DMAT_VISION_BASE_URL:-${base:-http://localhost:8080}}"

  if infer_up "$base"; then
    ai_info "推論伺服器已就緒 ✔ ($base)"
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1 || ! docker ps >/dev/null 2>&1; then
    ai_warn "推論伺服器未回應($base),且無法操作 docker。"
    ai_warn "若使用 hf / llama.cpp 模式請自行確認;否則辨識會降級為人工輸入。"
    return 0
  fi

  if docker inspect dmat-vllm >/dev/null 2>&1; then
    ai_info "推論伺服器未回應,嘗試啟動既有容器 dmat-vllm…"
    docker start dmat-vllm >/dev/null 2>&1 || true
    # 模型載入約 1~2 分鐘(權重已快取),最多等 3 分鐘
    for _ in $(seq 1 90); do
      if infer_up "$base"; then
        ai_info "推論伺服器已就緒 ✔"
        return 0
      fi
      sleep 2
    done
    ai_warn "推論伺服器仍未就緒,可能還在載入模型。"
    ai_warn "以 docker logs -f dmat-vllm 觀察,出現 'Application startup complete.' 即可用。"
  else
    ai_warn "推論伺服器未啟動,且找不到 dmat-vllm 容器。"
    ai_warn "請先執行:./scripts/start-vllm-docker.sh"
    ai_warn "(在那之前上傳的照片會降級為人工輸入模式)"
  fi
}

# 跨平台開啟瀏覽器
open_url(){
  if command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1 &
  elif command -v open >/dev/null; then open "$1" >/dev/null 2>&1 &
  fi
}

# --- 檢查必要工具 ---
command -v python3 >/dev/null || { err "找不到 python3，請先安裝 Python 3.10+"; exit 1; }
command -v dotnet  >/dev/null || { err "找不到 dotnet，請先安裝 .NET 8 SDK"; exit 1; }

# 引擎由 src/ai-service/.env 決定(由 scripts/setup-ocr.sh 產生);未設定則為 mock。
ENGINE="${DMAT_ENGINE:-$(sed -n 's/^DMAT_ENGINE=//p' "$AI_DIR/.env" 2>/dev/null | tail -1)}"
ENGINE="${ENGINE:-mock}"

# =============================================================
# 背景任務：AI 辨識服務整套流程(Python 環境、推論容器喚醒、
# 啟動 uvicorn)。全部包在同一個子行程裡,最後用 exec 換成
# uvicorn 本身,這樣 $! 抓到的 PID 從頭到尾都能用來關閉它。
# =============================================================
run_ai_stack(){
  if [ ! -d "$VENV" ]; then
    ai_info "首次執行：建立 Python 虛擬環境..."
    python3 -m venv "$VENV"
    ai_info "安裝相依套件...(第一次可能要幾分鐘,不影響網站使用)"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$AI_DIR/requirements.txt"
    ai_info "相依套件安裝完成 ✔"
  fi

  # 先確保推論伺服器活著,再啟動 AI 服務 —— 順序相反的話,
  # 服務起來的瞬間健康檢查會是失敗的,畫面上會閃一次誤導人的警示。
  ensure_inference

  ai_info "啟動 AI 辨識服務 → http://localhost:8100 (引擎:$ENGINE)"
  cd "$AI_DIR"
  exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8100
}

run_ai_stack &
AI_PID=$!

# 腳本結束(或 Ctrl+C)時一併關閉 AI 服務(不論它目前跑到哪個階段)
cleanup(){ info "關閉服務..."; kill "$AI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# --- 背景等待 AI 服務就緒後才提示 / 開啟其 API 文件,不擋網站 ---
(
  for _ in $(seq 1 600); do
    if curl -s -o /dev/null --noproxy '*' http://127.0.0.1:8100/docs; then
      ai_info "AI 服務已就緒 ✔  (API 文件：http://localhost:8100/docs)"
      # 明確警告模擬引擎:否則拍一整批照片後才發現全是同一份樣張假資料
      if curl -s --noproxy '*' http://127.0.0.1:8100/api/v1/health | grep -q '"isMock":true'; then
        ai_warn "⚠ 目前為模擬引擎：辨識結果是固定樣張假資料，與拍攝內容無關。"
        ai_warn "  要真的辨識照片，請執行 ./scripts/setup-ocr.sh 後重啟。"
      fi
      open_url "http://localhost:8100/docs"
      break
    fi
    sleep 1
  done
) &

# --- 背景等待 Web 就緒後自動開啟瀏覽器 ---
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null http://127.0.0.1:5100; then break; fi
    sleep 1
  done
  info "Web 已就緒，開啟瀏覽器..."
  open_url "http://localhost:5100"
) &

# --- 前景啟動 Web 應用 (綁 0.0.0.0，區網/手機可連) ---
# 這一段不等待 AI 服務或推論容器，開機後點桌面圖示就會直接開始啟動網站。
LAN_IP="$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '^127\.' | head -1 || true)"
info "啟動 Web 應用 → http://localhost:5100"
[ -n "$LAN_IP" ] && info "同網路裝置(手機)請連 → http://$LAN_IP:5100/Dashboard"
info "AI 辨識服務(引擎:$ENGINE)已在背景啟動中，就緒後會另行提示，不影響網站使用"
info "測試帳號：medic01 / leader01 / commander / admin   密碼：Dmat#2026"
cd "$WEB_DIR"
dotnet run --urls http://0.0.0.0:5100
# dotnet run 結束後，trap 會自動關閉 AI 服務
