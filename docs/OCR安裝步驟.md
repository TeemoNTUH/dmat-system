# 真實 OCR 安裝步驟(GB10 / DGX Spark)

把 AI 辨識服務從 `mock` 模擬引擎換成真的會看照片的 Chandra OCR 2。

- **環境**:Ubuntu 24.04 aarch64 + NVIDIA GB10(Blackwell / SM121)
- **需時**:約 30~60 分鐘,絕大部分在下載(容器數 GB + 模型權重約 10GB)
- **要不要重拍照片**:不用。已上傳的照片在覆核頁按「↻ 重新辨識」即可

---

## 步驟 0:確認起點

```bash
cd ~/dmat-system          # 換成你的專案路徑
./scripts/setup-ocr.sh
```

應該看到:

```
判定        : NVIDIA GB10 / DGX Spark 級平台
→ 因此 GB10 首選 NVIDIA 官方容器:./scripts/setup-ocr.sh docker
```

若「判定」是「一般平台」,表示 `nvidia-smi` 找不到或 GPU 未就緒,先處理驅動再繼續。

---

## 步驟 1:確認 Docker 可用(通常 DGX Spark 出廠已備)

```bash
docker ps
```

出現 `permission denied` 就加入 docker 群組:

```bash
sudo usermod -aG docker $USER
```

> ⚠ **`usermod` 不會影響已經開著的終端機。** 群組成員資格是登入時決定的,
> 執行完必須**登出再登入**(或至少在新終端機執行 `newgrp docker`,但那只對該視窗有效)。
> 這是這步最常見的失敗原因 —— 指令跑了、卻沒生效。

再確認一次:

```bash
docker ps          # 不用 sudo 就要能跑
```

若 `docker ps` 不行、但 `sudo docker ps` 可以 → 就是群組沒生效,登出再登入。
若兩個都不行 → daemon 沒起來:`sudo systemctl start docker`。

> **不建議用 `sudo` 跑容器繞過。** sudo 下的 `$HOME` 是 `/root`,模型會下載到
> `/root/.cache/huggingface`,等於那 10GB 要重抓一次,之後也容易混淆。

確認容器看得到 GPU:

```bash
docker run --rm --gpus all nvcr.io/nvidia/vllm:26.06-py3 nvidia-smi
```

> 這行會順便把映像拉下來(數 GB)。若失敗說找不到該標籤,到
> [NGC vLLM 容器目錄](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm)
> 查目前可用版本,後續步驟改用:
> `DMAT_NGC_VLLM_TAG=nvcr.io/nvidia/vllm:<版本> ./scripts/setup-ocr.sh docker`

---

## 步驟 2:準備模型下載權限(只有需要時)

Chandra 的權重是 modified OpenRAIL-M 授權,可能需要先在網頁上按同意:

1. 開 https://huggingface.co/datalab-to/chandra-ocr-2 ,若有授權同意鈕就按下去
2. 建一個 [Access Token](https://huggingface.co/settings/tokens)(read 權限即可)
3. 讓下載程序拿到 token:

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx
```

> 若步驟 4 下載時出現 401 / 403,就是漏了這步。
> 想長期保存可寫進 `~/.bashrc`,或改用 `hf auth login`。

---

## 步驟 3:執行安裝

```bash
./scripts/setup-ocr.sh docker
```

腳本會做四件事:

1. 建立 Python 虛擬環境並安裝 AI 服務相依(含 Pillow 影像前處理)
2. 確認 docker 可用、映像已拉取、容器內看得到 GPU
3. 產生 `scripts/start-vllm-docker.sh`(推論伺服器啟動腳本)
4. 寫入 `src/ai-service/.env`,把引擎設成 `vision`

看到 `[ OK ] 已寫入 …/.env(DMAT_ENGINE=vision)` 就成功了。

---

## 步驟 4:啟動推論伺服器

```bash
./scripts/start-vllm-docker.sh
```

**首次會下載約 10GB 權重,請耐心等。** 存到 `~/.cache/huggingface`,之後重啟不必重抓。

就緒訊號 —— 日誌出現這行:

```
INFO:     Application startup complete.
```

> **容器是背景常駐的**(`-d --restart unless-stopped`):
> - 關掉終端機**不會**把它帶走
> - 主機重開機後會**自動起來**
> - 容器崩潰也會**自動重試**
>
> 腳本啟動後會接著跟隨日誌,按 **Ctrl+C 只是停止看日誌,不會停掉伺服器**。
> 要真的停止:`docker stop dmat-vllm`(手動停掉後就不會自動重啟,直到你再啟動它)。
>
> 之後想看日誌:`docker logs -f dmat-vllm`

另開一個終端機驗證推論伺服器活著:

```bash
curl --noproxy '*' http://localhost:8080/v1/models
```

> 若這行沒回應,先看終端機 A 的訊息:是還在下載、還在載入模型,還是已經崩了?
> 崩了的話容器會結束,但日誌留著:`docker logs --tail 50 dmat-vllm`。
> 不確定就跑 `./scripts/diagnose-ocr.sh`,它會直接告訴你卡在哪一段。

---

## 步驟 5:啟動 DMAT

```bash
./start-dev.sh
```

> `start-dev.sh` 會**先檢查推論伺服器**再啟動 AI 服務:
> 端點沒回應但 `dmat-vllm` 容器存在時,會自動 `docker start` 並等它就緒(最多 3 分鐘);
> 容器根本不存在才會提示你去跑步驟 4。
> 因此日常使用只要跑 `./start-dev.sh` 就好,推論伺服器會自己被叫起來。

啟動訊息會顯示 `引擎:vision`。**若仍顯示 `引擎:mock`,表示 `.env` 沒被讀到**,
回去確認 `src/ai-service/.env` 內容。

---

## 步驟 6:驗證真的換掉了

```bash
curl --noproxy '*' http://localhost:8100/api/v1/health
```

要看到:

```json
{ "isMock": false, "engineReady": true, "engine": "datalab-to/chandra-ocr-2@http://localhost:8080(兩階段/chandra)" }
```

- `isMock: false` → 不再是模擬引擎 ✅
- `engineReady: true` → 推論伺服器連得到 ✅

拿一張你已經拍過的照片實測:

```bash
cd src/ai-service
ls ../Dmat.Web/app_data/images/202607/          # 挑一個檔名
.venv/bin/python tools/try_image.py ../Dmat.Web/app_data/images/202607/<檔名>.jpg
```

會印出引擎、前處理結果、以及辨識到幾欄。**首次推論較慢(數十秒)是正常的。**

---

## 步驟 7:把舊照片重跑一遍

1. 瀏覽器開 http://localhost:5100 ,以 `medic01` / `Dmat#2026` 登入
2. 進「覆核佇列」,點任一筆
3. 按右上角「**↻ 重新辨識**」

畫面上原本的紅色「⚠ 本結果來自模擬引擎」警示應該消失,欄位換成你照片的真實內容。

拍攝頁上方也應顯示綠色的 `✔ AI 辨識引擎已就緒`。

---

## 疑難排解

### 先跑一鍵診斷

```bash
./scripts/diagnose-ocr.sh
```

會沿著 `AI 服務(8100) → 推論伺服器(8080) → 容器 → 模型權重` 逐段檢查,
最後直接給判定與下一步。**遇到任何問題都先跑這個。**

### 「無法連線至推論服務 http://localhost:8080」

這個訊息代表引擎切換**已經成功**(不再是 mock),只差推論伺服器。三種可能:

| 診斷腳本的判定 | 意思 | 處理 |
|---|---|---|
| 推論伺服器尚未啟動 | 容器不存在,步驟 4 還沒做 | 跑 `./scripts/start-vllm-docker.sh`(容器存在的話,`./start-dev.sh` 會自動喚醒它) |
| 模型下載中 / vLLM 仍在啟動 | 容器在跑但還沒就緒 | 等,並用 `docker logs -f dmat-vllm` 看進度 |
| 容器啟動失敗 | vLLM 崩了 | 診斷腳本會直接指出是授權、架構不支援、還是記憶體問題 |

手動確認容器狀態:

```bash
docker ps -a --filter name=dmat-vllm      # 有沒有?狀態是 running 還是 Exited?
docker logs --tail 50 dmat-vllm           # 失敗原因
```

> 啟動腳本刻意**不加 `--rm`**,就是為了讓容器結束後日誌還查得到。

### 其他症狀

| 症狀 | 原因與處理 |
|---|---|
| `permission denied` 連不上 docker daemon | 未加入 docker 群組。做步驟 1,並**重開終端機** |
| 映像拉不到 / 找不到標籤 | 版本標籤已更新。查 NGC 目錄後用 `DMAT_NGC_VLLM_TAG=…` 指定 |
| 模型下載 401 / 403 | 沒接受授權或沒給 token。做步驟 2 |
| 容器內 `nvidia-smi` 看不到 GPU | NVIDIA Container Toolkit 未設定完成 |
| vLLM 說不支援模型架構 | 容器版本較舊、不認得 `qwen3_5`。改用備援模型(見下) |
| 記憶體不足但容量明明夠 | DGX Spark 統一記憶體特性。`sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` |
| health 仍 `isMock: true` | `.env` 沒生效,或環境變數 `DMAT_ENGINE=mock` 蓋掉了(環境變數優先) |
| `engineReady: false` | 終端機 A 的推論伺服器沒起來,或還在載入模型 |
| 辨識逾時 | 調高 `DMAT_VISION_TIMEOUT_S`,或降 `DMAT_PREPROCESS_MAX_EDGE`(如 1600) |
| 連不上但埠明明開著 | 系統設了 `HTTP_PROXY`/`ALL_PROXY`。服務端已不走代理;curl 測試請加 `--noproxy '*'` |

### 備援模型(Chandra 跑不起來時)

改用 NVIDIA 官方 DGX Spark 支援矩陣內**已驗證**的視覺模型,**程式碼不需修改**:

```bash
# 編輯 src/ai-service/.env,把 DMAT_VISION_MODEL 換成:
DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4
```

同時編輯 `scripts/start-vllm-docker.sh` 的 `MODEL=` 為同一個值,重啟兩邊即可。
服務會自動偵測到「非 Chandra 模型」,把轉寫提示從 Chandra 原生提示切換成
中文指示式提示(`/api/v1/health` 的 `detail.promptStyle` 會顯示 `generic`)。

辨識品質會低於 Chandra(通用 VLM vs OCR 專用模型),但能先讓整條流程跑起來。

### 想暫時切回模擬引擎(做介面測試時)

環境變數優先於 `.env`,所以不必改檔案:

```bash
DMAT_ENGINE=mock ./start-dev.sh
```

---

## 不想用 Docker 的替代路徑

需要自己先裝好 **aarch64 + CUDA 版的 torch**(⚠ 不要直接 `pip install torch`,
aarch64 會裝到 CPU 版),之後:

```bash
./scripts/setup-ocr.sh hf
./start-dev.sh
```

這條路不需要另跑推論伺服器,模型於服務啟動後在背景載入(數十秒),
`/api/v1/health` 的 `engineReady` 轉 `true` 即可用。
缺點是沒有 continuous batching,大量補傳時吞吐低於 vLLM。

---

## 相關文件

- [AI服務使用說明.md](AI服務使用說明.md) — 引擎組態、REST API、辨識品質調整
- [Web應用使用說明.md](Web應用使用說明.md) — 現場操作流程
