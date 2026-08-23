#!/usr/bin/env bash
# =============================================================================
# DMAT OCR 一鍵診斷
#
# 「無法連線至推論服務」有好幾種成因,靠猜很花時間。本腳本沿著整條鏈路
# 逐段檢查並直接給出判定與下一步。
#
#   瀏覽器 → Web(5100) → AI 服務(8100) → 推論伺服器(8080) → 模型權重
#
# 用法:./scripts/diagnose-ocr.sh
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AI_DIR="$ROOT/src/ai-service"
ENV_FILE="${DMAT_ENV_FILE:-$AI_DIR/.env}"
CONTAINER="dmat-vllm"

ok(){   printf '\033[1;32m  ✔\033[0m %s\n' "$1"; }
bad(){  printf '\033[1;31m  ✗\033[0m %s\n' "$1"; }
warn(){ printf '\033[1;33m  !\033[0m %s\n' "$1"; }
info(){ printf '    %s\n' "$1"; }
head_(){ printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# 判定收集:以「根因深度」排序,而不是檢查先後。
# 例如 Docker 權限不足會連帶造成推論伺服器與 engineReady 皆失敗,
# 若用先到先贏,使用者會被導去修最表層的症狀,白繞一圈。
# 數字越小越根本,報告時取最小者為主要判定,其餘列為附帶發現。
PRIO_DOCKER=10      # Docker 不可用 → 整條下游都不可能起來
PRIO_MODEL=20       # 模型權重問題
PRIO_INFER=30       # 推論伺服器
PRIO_ENGINE=40      # 引擎設定
PRIO_SERVICE=50     # AI 服務 / Web
FINDINGS=()
add_finding(){ FINDINGS+=("$1|$2|$3"); }   # 優先序|判定|下一步

get(){ curl -fsS --noproxy '*' --max-time "${2:-5}" "$1" 2>/dev/null; }

# --- 1. 設定 --------------------------------------------------------------
head_ "1. 引擎設定"
ENGINE="mock"; BASE_URL="http://localhost:8080"; MODEL="?"
if [[ -f "$ENV_FILE" ]]; then
  ok "找到設定檔:$ENV_FILE"
  ENGINE="$(sed -n 's/^DMAT_ENGINE=//p'          "$ENV_FILE" | tail -1)"; ENGINE="${ENGINE:-mock}"
  BASE_URL="$(sed -n 's/^DMAT_VISION_BASE_URL=//p' "$ENV_FILE" | tail -1)"; BASE_URL="${BASE_URL:-http://localhost:8080}"
  MODEL="$(sed -n 's/^DMAT_VISION_MODEL=//p'     "$ENV_FILE" | tail -1)"; MODEL="${MODEL:-?}"
else
  warn "找不到 $ENV_FILE(尚未執行 ./scripts/setup-ocr.sh docker?)"
fi
# 環境變數優先
[[ -n "${DMAT_ENGINE:-}" ]] && { ENGINE="$DMAT_ENGINE"; warn "環境變數 DMAT_ENGINE=$ENGINE 覆寫了設定檔"; }
[[ -n "${DMAT_VISION_BASE_URL:-}" ]] && BASE_URL="$DMAT_VISION_BASE_URL"
info "引擎:$ENGINE   模型:$MODEL   推論端點:$BASE_URL"
[[ "$ENGINE" == "mock" ]] && add_finding $PRIO_ENGINE "目前仍是模擬引擎" "./scripts/setup-ocr.sh docker"

PORT="$(sed -E 's#.*:([0-9]+)/?$#\1#' <<<"$BASE_URL")"
[[ "$PORT" =~ ^[0-9]+$ ]] || PORT=8080

# --- 2. 代理設定 -----------------------------------------------------------
head_ "2. 代理設定"
PROXY_SET=""
for v in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
  [[ -n "${!v:-}" ]] && PROXY_SET="$PROXY_SET $v=${!v}"
done
if [[ -n "$PROXY_SET" ]]; then
  warn "偵測到代理環境變數:$PROXY_SET"
  info "服務端已設 trust_env=False 不受影響;但你自己用 curl 測試時要加 --noproxy '*'"
else
  ok "未設定 HTTP 代理"
fi

# --- 3. AI 服務(8100) -----------------------------------------------------
head_ "3. AI 辨識服務(8100)"
HEALTH="$(get http://127.0.0.1:8100/api/v1/health 8)"
if [[ -z "$HEALTH" ]]; then
  bad "AI 服務未回應"
  add_finding $PRIO_SERVICE "AI 服務(8100)沒起來" "./start-dev.sh"
else
  ok "AI 服務有回應"
  grep -q '"isMock":true'  <<<"$HEALTH" && warn "isMock=true(模擬引擎)" || ok "isMock=false(真實引擎)"
  grep -q '"engineReady":true' <<<"$HEALTH" && ok "engineReady=true" || bad "engineReady=false(連不到推論伺服器)"
fi

# --- 4. 推論伺服器(8080) --------------------------------------------------
head_ "4. 推論伺服器($BASE_URL)"
MODELS="$(get "$BASE_URL/v1/models" 8)"
INFER_UP=0
if [[ -n "$MODELS" ]]; then
  INFER_UP=1
  ok "推論伺服器已就緒"
  info "已載入:$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]*"' <<<"$MODELS" \
        | sed -E 's/.*"([^"]*)"$/\1/' | head -3 | tr '\n' ' ')"
else
  bad "連不到 $BASE_URL/v1/models"
fi

# 埠是否被別的東西佔用
if command -v ss >/dev/null 2>&1; then
  LISTENER="$(ss -ltnp 2>/dev/null | grep -E ":$PORT\b" | head -1)"
  if [[ -n "$LISTENER" && $INFER_UP -eq 0 ]]; then
    warn "埠 $PORT 有其他程序在聽,但不是可用的 vLLM:"
    info "$LISTENER"
  fi
fi

# --- 5. 容器狀態 -----------------------------------------------------------
head_ "5. 推論容器($CONTAINER)"
if ! command -v docker >/dev/null 2>&1; then
  warn "找不到 docker(若你用 hf / llama.cpp 模式可忽略本節)"
elif ! docker ps >/dev/null 2>&1; then
  bad "無法連線 Docker daemon"
  # 區分「只是缺 docker 群組」與「daemon 根本沒跑」—— 處理方式完全不同
  if sudo -n docker ps >/dev/null 2>&1; then
    info "但 sudo docker ps 可以 → daemon 正常,只是你的帳號不在 docker 群組"
    add_finding $PRIO_DOCKER "你的帳號不在 docker 群組" \
      "sudo usermod -aG docker \$USER,然後【登出再登入】(或在新終端機執行 newgrp docker)"
  elif systemctl is-active --quiet docker 2>/dev/null; then
    info "docker 服務是 active,但目前使用者連不上 socket"
    add_finding $PRIO_DOCKER "你的帳號不在 docker 群組" \
      "sudo usermod -aG docker \$USER,然後【登出再登入】(或在新終端機執行 newgrp docker)"
  else
    info "docker 服務似乎未啟動"
    add_finding $PRIO_DOCKER "Docker daemon 未啟動或無權限" \
      "sudo systemctl start docker;若仍不行:sudo usermod -aG docker \$USER 後登出再登入"
  fi
  info "驗證方式(不用改群組也能先確認 daemon 活著):sudo docker ps"
else
  STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null)"
  if [[ -z "$STATE" ]]; then
    bad "容器不存在 —— 推論伺服器還沒啟動過"
    add_finding $PRIO_INFER "推論伺服器尚未啟動" "在另一個終端機執行:./scripts/start-vllm-docker.sh"
  elif [[ "$STATE" == "running" ]]; then
    ok "容器執行中"
    LOG="$(docker logs --tail 200 "$CONTAINER" 2>&1)"
    if grep -q "Application startup complete" <<<"$LOG"; then
      ok "vLLM 已完成啟動"
      [[ $INFER_UP -eq 0 ]] && add_finding $PRIO_INFER \
        "容器已就緒但主機連不到,可能是埠對應不符" \
        "檢查 docker port $CONTAINER,確認對應到 $PORT"
    elif grep -qiE "Downloading|fetching .* files|%\|" <<<"$LOG"; then
      warn "模型仍在下載中(首次約 10GB),請等候"
      add_finding $PRIO_INFER "模型下載中" "等待,並以 docker logs -f $CONTAINER 觀察進度"
    else
      warn "vLLM 啟動中(載入模型與編譯 kernel 可能要數分鐘)"
      add_finding $PRIO_INFER "vLLM 仍在啟動" "docker logs -f $CONTAINER 等待 'Application startup complete.'"
    fi
    info "最後幾行日誌:"
    tail -5 <<<"$LOG" | sed 's/^/      /'
  else
    EXIT_CODE="$(docker inspect -f '{{.State.ExitCode}}' "$CONTAINER" 2>/dev/null)"
    bad "容器已結束(狀態 $STATE,退出碼 $EXIT_CODE)"
    LOG="$(docker logs --tail 400 "$CONTAINER" 2>&1)"

    if grep -qiE "401|403|gated|awaiting a review|access to model" <<<"$LOG"; then
      add_finding $PRIO_MODEL "模型下載被拒(需接受授權)" \
        "到 https://huggingface.co/$MODEL 按同意,再 export HF_TOKEN=... 後重跑 ./scripts/start-vllm-docker.sh"
    elif grep -qiE "not supported|unsupported|unrecognized|no module named|KeyError.*architectures|ValueError.*architecture" <<<"$LOG"; then
      add_finding $PRIO_MODEL "此 vLLM 版本不支援該模型架構" \
        "改用備援模型:編輯 .env 與 start-vllm-docker.sh,設 nvidia/Qwen2.5-VL-7B-Instruct-NVFP4"
    elif grep -qiE "out of memory|OOM|CUDA error: out of memory" <<<"$LOG"; then
      add_finding $PRIO_INFER "記憶體不足" \
        "先清快取 sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches',並把 --max-model-len 降到 8192"
    elif grep -qiE "SM_?121|sm_121|no kernel image|compute capability" <<<"$LOG"; then
      add_finding $PRIO_INFER "GPU 架構(SM121)不相容" \
        "改用較新的 NGC 容器:DMAT_NGC_VLLM_TAG=nvcr.io/nvidia/vllm:<新版> ./scripts/setup-ocr.sh docker"
    elif grep -qiE "address already in use|port is already allocated" <<<"$LOG"; then
      add_finding $PRIO_INFER "埠 $PORT 已被占用" "改埠或停掉占用的程序"
    else
      add_finding $PRIO_INFER "容器啟動失敗(原因見日誌)" "docker logs $CONTAINER | tail -50"
    fi

    info "日誌尾段(找 Error/Traceback):"
    grep -iE "error|exception|traceback|failed|refus" <<<"$LOG" | tail -8 | sed 's/^/      /'
    [[ -z "$(grep -iE "error|exception|traceback|failed" <<<"$LOG")" ]] && tail -8 <<<"$LOG" | sed 's/^/      /'
  fi

  # 映像
  IMG="$(sed -n 's/^IMAGE="\(.*\)"$/\1/p' "$ROOT/scripts/start-vllm-docker.sh" 2>/dev/null | head -1)"
  if [[ -n "$IMG" ]]; then
    docker image inspect "$IMG" >/dev/null 2>&1 \
      && ok "映像已存在:$IMG" \
      || { bad "映像不存在:$IMG"; add_finding $PRIO_INFER "映像尚未拉取" "docker pull $IMG"; }
  fi
fi

# --- 6. 模型快取 -----------------------------------------------------------
head_ "6. 模型權重快取"
CACHE="${HF_HOME:-$HOME/.cache/huggingface}/hub"
# 期望大小:chandra-ocr-2 為 5B BF16,約 10GB。
# 若只有數十 MB,表示只抓到 config/tokenizer/processor,權重根本還沒下載 ——
# 這常見於只跑過 setup-ocr.sh hf 的預抓步驟,或下載中途被中斷。
MIN_WEIGHT_MB=1000
if [[ -d "$CACHE" ]]; then
  SNAP="$(find "$CACHE" -maxdepth 1 -type d -name "models--*" 2>/dev/null | head -5)"
  if [[ -n "$SNAP" ]]; then
    while read -r d; do
      [[ -z "$d" ]] && continue
      SIZE_MB="$(du -sm "$d" 2>/dev/null | cut -f1)"
      NAME="$(basename "$d")"
      if [[ "${SIZE_MB:-0}" -lt $MIN_WEIGHT_MB ]]; then
        warn "$NAME  僅 ${SIZE_MB}MB —— 只有設定檔,模型權重尚未下載完成"
        # 有東西下載得下來 → 網路與授權沒問題,純粹是還沒抓權重
        info "(能抓到設定檔代表 HuggingFace 連得上、授權也沒擋,只是權重還沒開始下載)"
        add_finding $PRIO_MODEL "模型權重尚未下載完成(目前僅 ${SIZE_MB}MB,應約 10GB)" \
          "啟動推論伺服器時會自動下載:./scripts/start-vllm-docker.sh"
      else
        ok "$NAME  $(du -sh "$d" 2>/dev/null | cut -f1)"
      fi
    done <<<"$SNAP"
  else
    warn "快取目錄存在但沒有已下載的模型"
  fi
else
  warn "尚未建立 $CACHE(模型還沒開始下載)"
fi
# 用 sudo 跑容器時,HOME 會變成 /root,快取路徑不同、會重抓一次 10GB
if [[ -d /root/.cache/huggingface/hub && "$HOME" != "/root" ]]; then
  warn "偵測到 /root/.cache/huggingface —— 你可能用 sudo 跑過容器"
  info "sudo 會用 root 的快取,等於重抓一次 10GB。建議改用 docker 群組,或在啟動時指定 HF_HOME"
fi

# 保底:推論端點連不上但前面沒歸因到具體原因(例如未用 Docker 的部署方式)
if [[ $INFER_UP -eq 0 && "$ENGINE" != "mock" && "$ENGINE" != "chandra_hf" ]]; then
  HAS_UPSTREAM=0
  for f in ${FINDINGS[@]+"${FINDINGS[@]}"}; do
    [[ "$f" == "$PRIO_INFER|"* || "$f" == "$PRIO_DOCKER|"* ]] && HAS_UPSTREAM=1
  done
  [[ $HAS_UPSTREAM -eq 0 ]] && add_finding $PRIO_INFER "推論伺服器沒有在 $BASE_URL 上運作" \
    "在另一個終端機啟動它:./scripts/start-vllm-docker.sh(或你自己的 vLLM/llama.cpp 啟動方式)"
fi

# --- 判定 -----------------------------------------------------------------
head_ "判定"
if [[ ${#FINDINGS[@]} -eq 0 ]]; then
  if [[ $INFER_UP -eq 1 ]] && grep -q '"engineReady":true' <<<"${HEALTH:-}"; then
    printf '\033[1;32m  整條鏈路正常。\033[0m\n'
    info "若辨識結果仍不理想,用下列指令看模型實際讀到什麼:"
    info "  cd src/ai-service && .venv/bin/python tools/try_image.py <照片> --raw"
  else
    printf '  尚無明確判定,請檢視上方各節。\n'
  fi
else
  # 依根因深度排序:先修最根本的,其餘症狀往往會一起消失
  SORTED="$(printf '%s\n' "${FINDINGS[@]}" | sort -t'|' -k1,1n)"
  MAIN="$(head -1 <<<"$SORTED")"
  printf '\033[1;31m  主要問題:%s\033[0m\n' "$(cut -d'|' -f2 <<<"$MAIN")"
  printf '\033[1m  下一步:\033[0m%s\n' "$(cut -d'|' -f3 <<<"$MAIN")"

  OTHERS="$(tail -n +2 <<<"$SORTED")"
  if [[ -n "$OTHERS" ]]; then
    printf '\n  其他發現(多半會在修好主要問題後一併解決):\n'
    while IFS='|' read -r _p v n; do
      [[ -z "$v" ]] && continue
      printf '    · %s\n      → %s\n' "$v" "$n"
    done <<<"$OTHERS"
  fi
fi
echo
