#!/usr/bin/env bash
# =============================================================================
# DMAT 真實 OCR 引擎安裝腳本
#
# 把 AI 辨識服務從「mock 模擬引擎」切換到真的會看照片的 Chandra OCR 2。
#
# 用法:
#   ./scripts/setup-ocr.sh              # 偵測環境並給出建議
#   ./scripts/setup-ocr.sh docker       # NVIDIA 官方 NGC 容器(GB10/DGX Spark 首選)
#   ./scripts/setup-ocr.sh vllm         # pip 安裝 vLLM(非 GB10 平台適用)
#   ./scripts/setup-ocr.sh hf           # 本機 transformers,不另跑伺服器
#   ./scripts/setup-ocr.sh check        # 只檢查現況
#
# 模型授權提醒:datalab-to/chandra-ocr-2 權重為 modified OpenRAIL-M,
# 研究/個人/年營收未達 200 萬美元之新創可免費使用,其他商業用途需另洽授權。
# 專案 README 已列「開源授權尚未定案」,正式發布前請一併確認此項。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AI_DIR="$ROOT/src/ai-service"
VENV="$AI_DIR/.venv"
PY="$VENV/bin/python"
MODEL_ID="${DMAT_HF_MODEL_ID:-datalab-to/chandra-ocr-2}"
VLLM_PORT="${DMAT_VLLM_PORT:-8080}"
# NVIDIA 官方 vLLM 容器(ARM64 + Blackwell)。最新版本見:
# https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm
NGC_VLLM_TAG="${DMAT_NGC_VLLM_TAG:-nvcr.io/nvidia/vllm:26.06-py3}"

c_info(){ printf '\033[1;34m[DMAT]\033[0m %s\n' "$1"; }
c_ok(){   printf '\033[1;32m[ OK ]\033[0m %s\n' "$1"; }
c_warn(){ printf '\033[1;33m[WARN]\033[0m %s\n' "$1"; }
c_err(){  printf '\033[1;31m[ERR ]\033[0m %s\n' "$1" >&2; }
c_head(){ printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# -----------------------------------------------------------------------------
# 環境偵測
# -----------------------------------------------------------------------------
detect() {
  ARCH="$(uname -m)"
  IS_GB10=0
  GPU_NAME=""
  COMPUTE_CAP=""

  if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
    COMPUTE_CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1)"
  fi
  # GB10(DGX Spark):Grace CPU 為 10×Cortex-X925 + 10×Cortex-A725,GPU 運算能力 12.1(SM121)
  if grep -qi 'cortex-x925' /proc/cpuinfo 2>/dev/null \
     || [[ "$GPU_NAME" == *GB10* ]] || [[ "$COMPUTE_CAP" == 12.1* ]]; then
    IS_GB10=1
  fi

  c_head "環境偵測"
  echo "  架構        : $ARCH"
  echo "  GPU         : ${GPU_NAME:-（未偵測到 nvidia-smi）}"
  echo "  Compute cap : ${COMPUTE_CAP:-未知}"
  echo "  判定        : $([[ $IS_GB10 -eq 1 ]] && echo 'NVIDIA GB10 / DGX Spark 級平台' || echo '一般平台')"

  if [[ $IS_GB10 -eq 1 ]]; then
    c_info "GB10 統一記憶體充裕,BF16 的 5B 模型(約 10GB)可直接跑,不需量化。"
    c_warn "GB10 為 SM121:PyPI 的標準 vLLM wheel 多半不支援(SM_121a not recognized),"
    c_warn "自行從原始碼建置需要 LLVM/Triton 的 ARM64 patch。"
    c_info "→ 因此 GB10 首選 NVIDIA 官方容器:./scripts/setup-ocr.sh docker"
  fi
}

ensure_venv() {
  if [[ ! -x "$PY" ]]; then
    c_info "建立 Python 虛擬環境…"
    python3 -m venv "$VENV" || { c_err "建立 venv 失敗"; exit 1; }
  fi
  "$PY" -m pip install -q --upgrade pip
  c_info "安裝 AI 服務基礎相依(含 Pillow 影像前處理)…"
  "$PY" -m pip install -q -r "$AI_DIR/requirements.txt" || { c_err "基礎相依安裝失敗"; exit 1; }
  c_ok "基礎相依就緒"
}

have_torch_cuda() {
  "$PY" - <<'EOF' 2>/dev/null
import sys
try:
    import torch
except ImportError:
    sys.exit(1)
sys.exit(0 if torch.cuda.is_available() else 2)
EOF
}

# -----------------------------------------------------------------------------
# 模式零:NVIDIA 官方 NGC 容器(GB10/DGX Spark 首選)
#
# 依 NVIDIA/dgx-spark-playbooks 的 vLLM playbook:官方容器已為 ARM64 + Blackwell
# 預先建置,直接 docker run 即可,不需處理 SM_121a 的 LLVM/Triton patch。
# -----------------------------------------------------------------------------
setup_docker() {
  ensure_venv

  c_head "檢查 Docker 與 NVIDIA Container Toolkit"
  if ! command -v docker >/dev/null 2>&1; then
    c_err "找不到 docker。DGX Spark 出廠應已安裝;請確認後重試。"
    exit 1
  fi
  if ! docker ps >/dev/null 2>&1; then
    c_err "無法連線 Docker daemon(權限不足?)。請執行:"
    echo "    sudo usermod -aG docker \$USER && newgrp docker"
    exit 1
  fi
  c_ok "docker 可用"

  # 先明確拉取(映像數 GB,讓進度看得見),再驗證容器內能否看到 GPU
  if ! docker image inspect "$NGC_VLLM_TAG" >/dev/null 2>&1; then
    c_info "拉取映像:$NGC_VLLM_TAG(數 GB,請稍候)"
    docker pull "$NGC_VLLM_TAG" || {
      c_err "映像拉取失敗。若為認證問題,請先 docker login nvcr.io;"
      c_err "或到 https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm 確認可用版本標籤,"
      c_err "再以 DMAT_NGC_VLLM_TAG=nvcr.io/nvidia/vllm:<版本> 重跑本腳本。"
      exit 1
    }
  else
    c_ok "映像已存在:$NGC_VLLM_TAG"
  fi

  if docker run --rm --gpus all "$NGC_VLLM_TAG" nvidia-smi -L 2>/dev/null | grep -q GPU; then
    c_ok "容器內可存取 GPU"
  else
    c_err "容器內看不到 GPU。請確認 NVIDIA Container Toolkit 已安裝且設定完成:"
    echo "    docker run --rm --gpus all $NGC_VLLM_TAG nvidia-smi"
    exit 1
  fi

  # 產生啟動腳本
  cat > "$ROOT/scripts/start-vllm-docker.sh" <<EOF
#!/usr/bin/env bash
# 以 NVIDIA 官方容器啟動 Chandra OCR 2 推論伺服器(OpenAI 相容)。
# 由 scripts/setup-ocr.sh docker 產生;可自行編輯調整參數。
#
# 容器以「背景常駐 + 自動重啟」方式執行:
#   -d                        背景執行,關掉終端機不會把它帶走
#   --restart unless-stopped  主機重開機後自動起來;容器崩潰也會自動重試
#                             (但你手動 docker stop 之後就不會自己再起來)
#
# 現場沒有人會記得「先開推論伺服器」,所以預設讓它自己活著。
#
# 首次啟動會下載約 10GB 權重到 ~/.cache/huggingface(已掛載進容器,重啟不必重抓)。
# 若下載出現 401/403,表示模型需要接受授權:先到模型頁按同意,
# 再於主機執行 hf auth login(或設好 HF_TOKEN)後重跑本腳本。
set -euo pipefail

IMAGE="$NGC_VLLM_TAG"
MODEL="$MODEL_ID"
PORT="$VLLM_PORT"
NAME="dmat-vllm"

info(){ printf '\033[1;34m[vLLM]\033[0m %s\n' "\$1"; }

# 先清掉上一次的同名容器(日誌保留到這一刻,方便查上次為何結束)
docker rm -f "\$NAME" >/dev/null 2>&1 || true

# 參數說明:
#   -p PORT:8000       容器內 vLLM 聽 8000,對應到主機 \$PORT(與 .env 的 BASE_URL 一致)
#   --max-model-len    整頁表單轉寫較長,且需容納影像 token;過大會多佔記憶體
docker run -d --name "\$NAME" \\
  --restart unless-stopped \\
  --gpus all \\
  -p "\$PORT":8000 \\
  -v "\$HOME/.cache/huggingface":/root/.cache/huggingface \\
  -e HF_TOKEN="\${HF_TOKEN:-}" \\
  "\$IMAGE" \\
  vllm serve "\$MODEL" \\
    --served-model-name "\$MODEL" \\
    --max-model-len 16384 >/dev/null

info "容器已在背景啟動(\$NAME),主機埠 \$PORT"
info "首次啟動需下載約 10GB 權重;之後僅需載入模型(約 1~2 分鐘)"
echo
info "以下開始跟隨日誌。就緒訊號:Application startup complete."
info "按 Ctrl+C 只會停止看日誌,不會停掉伺服器。"
info "要真的停止請執行:docker stop \$NAME"
echo

exec docker logs -f "\$NAME"
EOF
  chmod +x "$ROOT/scripts/start-vllm-docker.sh"
  c_ok "已產生 scripts/start-vllm-docker.sh"

  write_env "vision"
  c_head "接下來"
  cat <<EOF
  1) 終端機 A:./scripts/start-vllm-docker.sh     # 首次會下載約 10GB 權重
     看到 "Application startup complete" 即就緒
  2) 終端機 B:./start-dev.sh
  3) 驗證:curl --noproxy '*' http://localhost:8100/api/v1/health
           確認 "isMock": false 且 "engineReady": true

  若 vLLM 回報不支援 chandra-ocr-2 的模型架構(容器版本較舊),改用官方支援矩陣
  內已驗證的視覺模型作為備援,程式端不需修改:
     DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4
  (本服務會自動改用通用轉寫提示,見 DMAT_PROMPT_STYLE)

  DGX Spark 為統一記憶體(UMA),若出現記憶體不足但實際容量足夠,清一下快取:
     sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
EOF
}

# -----------------------------------------------------------------------------
# 模式一:pip 安裝 vLLM(非 GB10 平台)
# -----------------------------------------------------------------------------
setup_vllm() {
  ensure_venv
  if [[ ${IS_GB10:-0} -eq 1 ]]; then
    c_warn "偵測到 GB10:pip 版 vLLM 很可能因 SM121 失敗,建議改用 ./scripts/setup-ocr.sh docker"
  fi
  c_head "安裝 vLLM"
  if "$PY" -c 'import vllm' 2>/dev/null; then
    c_ok "已安裝 vLLM($("$PY" -c 'import vllm;print(vllm.__version__)' 2>/dev/null))"
  else
    c_info "嘗試以 pip 安裝 vLLM(GB10/SM121 可能失敗,見上方警告)…"
    if ! "$PY" -m pip install -q vllm; then
      c_err "vLLM 安裝失敗。"
      c_info "GB10 建議改走容器,或直接用本機模式:./scripts/setup-ocr.sh hf"
      exit 1
    fi
  fi

  cat > "$ROOT/scripts/start-vllm.sh" <<EOF
#!/usr/bin/env bash
# 啟動 Chandra OCR 2 推論伺服器(OpenAI 相容,供 DMAT AI 服務呼叫)
set -euo pipefail
exec "$PY" -m vllm.entrypoints.openai.api_server \\
  --model "$MODEL_ID" \\
  --served-model-name "$MODEL_ID" \\
  --port "$VLLM_PORT" \\
  --max-model-len 16384 \\
  --limit-mm-per-prompt '{"image":1}'
EOF
  chmod +x "$ROOT/scripts/start-vllm.sh"
  c_ok "已產生 scripts/start-vllm.sh"

  write_env "vision"
  c_head "接下來"
  cat <<EOF
  1) 終端機 A:./scripts/start-vllm.sh          # 首次會下載約 10GB 權重
  2) 終端機 B:./start-dev.sh                    # AI 服務會自動讀取 ai-service/.env
  3) 開 http://localhost:8100/api/v1/health,確認 "isMock": false
EOF
}

# -----------------------------------------------------------------------------
# 模式二:本機 transformers
# -----------------------------------------------------------------------------
setup_hf() {
  ensure_venv
  c_head "安裝本機推論相依"

  have_torch_cuda; rc=$?
  case $rc in
    0) c_ok "已安裝 torch 且 CUDA 可用" ;;
    2) c_warn "已安裝 torch 但 CUDA 不可用 — 辨識會落到 CPU,單張可能數分鐘。" ;;
    *)
      c_warn "尚未安裝 torch。"
      if [[ "$(uname -m)" == "aarch64" ]]; then
        c_err "aarch64 + CUDA 的 torch 請勿直接 pip install torch(會裝到 CPU 版或失敗)。"
        c_info "DGX Spark / GB10 請依 NVIDIA 官方指引安裝對應 CUDA 版本的 torch 後,再重跑本腳本。"
        exit 1
      fi
      c_info "安裝 torch…"
      "$PY" -m pip install -q torch || { c_err "torch 安裝失敗"; exit 1; }
      ;;
  esac

  c_info "安裝 chandra-ocr[hf] 與 transformers…"
  "$PY" -m pip install -q 'chandra-ocr[hf]' || {
    c_warn "chandra-ocr[hf] 安裝失敗,改裝 transformers(引擎僅用到 transformers 介面)…"
    "$PY" -m pip install -q 'transformers>=4.57' accelerate || { c_err "transformers 安裝失敗"; exit 1; }
  }
  c_ok "本機推論相依就緒"

  c_info "預先下載模型權重(約 10GB,可 Ctrl+C 中止,首次辨識時會自動續傳)…"
  "$PY" - <<EOF || c_warn "預先下載未完成,首次辨識時會自動下載。"
from transformers import AutoProcessor
AutoProcessor.from_pretrained("$MODEL_ID")
print("processor ok")
EOF

  write_env "chandra_hf"
  c_head "接下來"
  cat <<EOF
  1) ./start-dev.sh                              # AI 服務會自動讀取 ai-service/.env
  2) 模型於服務啟動後於背景載入(數十秒);/api/v1/health 的 engineReady 轉 true 即可用
  3) 開 http://localhost:8100/api/v1/health,確認 "isMock": false
EOF
}

# -----------------------------------------------------------------------------
# 產生 .env
# -----------------------------------------------------------------------------
write_env() {
  local engine="$1"
  local env_file="$AI_DIR/.env"
  if [[ -f "$env_file" ]]; then
    cp "$env_file" "$env_file.bak"
    c_info "既有 .env 已備份為 .env.bak"
  fi
  {
    echo "# 由 scripts/setup-ocr.sh 產生($(date '+%Y-%m-%d %H:%M'))"
    echo "DMAT_ENGINE=$engine"
    if [[ "$engine" == "vision" ]]; then
      echo "DMAT_VISION_BASE_URL=http://localhost:$VLLM_PORT"
      echo "DMAT_VISION_MODEL=$MODEL_ID"
    else
      echo "DMAT_HF_MODEL_ID=$MODEL_ID"
    fi
    echo "DMAT_TWO_STAGE=1"
    echo "# 轉寫提示風格:auto(依模型自動)/ chandra / generic"
    echo "DMAT_PROMPT_STYLE=auto"
    echo "DMAT_PREPROCESS=1"
    echo "DMAT_PREPROCESS_MAX_EDGE=2000"
    echo "# 淺色手寫/現場光線不均時可開啟自動對比:DMAT_PREPROCESS_ENHANCE=1"
    echo "# 除錯用(回傳模型原始轉寫,含個資,正式環境請關閉):DMAT_RETURN_RAW=1"
  } > "$env_file"
  c_ok "已寫入 $env_file(DMAT_ENGINE=$engine)"
}

# -----------------------------------------------------------------------------
# 檢查
# -----------------------------------------------------------------------------
do_check() {
  c_head "AI 服務狀態"
  local url="http://127.0.0.1:8100/api/v1/health"
  if ! command -v curl >/dev/null; then c_warn "找不到 curl,略過"; return; fi
  local body
  body="$(curl -fsS --noproxy '*' "$url" 2>/dev/null)" || { c_warn "AI 服務未啟動($url)"; return; }
  echo "$body"
  if grep -q '"isMock":true' <<<"$body"; then
    c_err "目前仍是模擬引擎 —— 辨識結果為樣張假資料,與照片無關。"
    c_info "執行 ./scripts/setup-ocr.sh vllm 或 hf 後重啟 AI 服務。"
  else
    c_ok "已使用真實引擎。"
  fi
}

# -----------------------------------------------------------------------------
case "${1:-detect}" in
  docker) detect; setup_docker ;;
  vllm)   detect; setup_vllm ;;
  hf)     detect; setup_hf ;;
  check)  do_check ;;
  detect|"")
    detect
    do_check
    c_head "建議"
    if [[ ${IS_GB10:-0} -eq 1 ]]; then
      cat <<'EOF'
  GB10 / DGX Spark 建議順序:
    1. ./scripts/setup-ocr.sh docker  ← 首選。NVIDIA 官方 ARM64+Blackwell 容器,
                                        避開 SM_121a 的 LLVM/Triton patch 問題
    2. ./scripts/setup-ocr.sh hf      ← 若不想用 Docker。需先自行裝好 aarch64+CUDA 版 torch
    3. ./scripts/setup-ocr.sh vllm    ← 不建議:pip 版 vLLM 多半不支援 SM121
EOF
    else
      cat <<'EOF'
  真實辨識:
    ./scripts/setup-ocr.sh vllm    ← 有 NVIDIA GPU,要高吞吐
    ./scripts/setup-ocr.sh hf      ← 元件最少,單張逐一辨識
    ./scripts/setup-ocr.sh docker  ← 有 Docker + NVIDIA Container Toolkit
EOF
    fi
    ;;
  *) c_err "未知參數:$1(可用:docker / vllm / hf / check / detect)"; exit 1 ;;
esac
