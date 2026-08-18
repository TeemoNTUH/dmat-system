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

IMAGE="nvcr.io/nvidia/vllm:26.06-py3"
MODEL="datalab-to/chandra-ocr-2"
PORT="8080"
NAME="dmat-vllm"

info(){ printf '\033[1;34m[vLLM]\033[0m %s\n' "$1"; }

# 先清掉上一次的同名容器(日誌保留到這一刻,方便查上次為何結束)
docker rm -f "$NAME" >/dev/null 2>&1 || true

# 參數說明:
#   -p PORT:8000       容器內 vLLM 聽 8000,對應到主機 $PORT(與 .env 的 BASE_URL 一致)
#   --max-model-len    整頁表單轉寫較長,且需容納影像 token;過大會多佔記憶體
docker run -d --name "$NAME" \
  --restart unless-stopped \
  --gpus all \
  -p "$PORT":8000 \
  -v "$HOME/.cache/huggingface":/root/.cache/huggingface \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  "$IMAGE" \
  vllm serve "$MODEL" \
    --served-model-name "$MODEL" \
    --max-model-len 16384 >/dev/null

info "容器已在背景啟動($NAME),主機埠 $PORT"
info "首次啟動需下載約 10GB 權重;之後僅需載入模型(約 1~2 分鐘)"
echo
info "以下開始跟隨日誌。就緒訊號:Application startup complete."
info "按 Ctrl+C 只會停止看日誌,不會停掉伺服器。"
info "要真的停止請執行:docker stop $NAME"
echo

exec docker logs -f "$NAME"
