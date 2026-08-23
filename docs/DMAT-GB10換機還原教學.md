# DMAT 系統 GB10 換機還原教學

適用情境：DGX Spark（GB10，Ubuntu 24.04 aarch64）主機更換後，要在新機器上把 DMAT 系統（含真實 OCR 引擎 Chandra OCR 2）重新裝回去、接回原本可用的狀態。

本文件依實際換機還原過程整理，包含實際遇到的錯誤與排除方式，供其他人照著操作時對照。

---

## 前置準備

- 新機器一樣是 Ubuntu 24.04 aarch64 + NVIDIA GB10（Blackwell / SM121）
- 專案資料夾（例如 `dmat-system-main`）已還原到 `~/Desktop/` 底下
- 有 sudo 權限的帳號
- 網路連線正常（安裝過程需下載容器映像數 GB + 模型權重約 10GB）

預估總耗時：30～60 分鐘，大部分時間在下載。

---

## 步驟 0：進入專案目錄，確認平台判定

```bash
cd ~/Desktop/dmat-system-main
./scripts/setup-ocr.sh
```

應該看到：

```
判定        : NVIDIA GB10 / DGX Spark 級平台
→ 因此 GB10 首選 NVIDIA 官方容器：./scripts/setup-ocr.sh docker
```

> 若「判定」顯示「一般平台」，代表 `nvidia-smi` 找不到或 GPU 未就緒，先處理驅動再往下走。

### ⚠️ 實際遇到的錯誤 1：腳本沒有執行權限

```
bash: ./scripts/setup-ocr.sh: 拒絕不符權限的操作
```

**原因**：換機還原（例如用壓縮檔搬移、或用某些同步工具複製）常會遺失檔案原本的「可執行」權限位元，這跟 Linux 使用者權限、sudo 無關。

**解法**：先幫整個專案的腳本補回執行權限，之後就不會再跳這個錯誤：

```bash
chmod +x start-dev.sh scripts/*.sh
```

或者不想改權限，直接用 `bash` 執行也可以：

```bash
bash scripts/setup-ocr.sh
```

---

## 步驟 1：確認 Docker 可用

```bash
docker ps
```

### ⚠️ 實際遇到的錯誤 2：連不上 Docker daemon

```
permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock
```

**原因**：新機器上的使用者帳號還沒加入 `docker` 群組（換機是全新系統帳號，不會沿用舊機器的群組設定）。

**解法**：

```bash
sudo usermod -aG docker $USER
```

> ⚠️ **這行指令對「目前已經開著」的終端機沒有作用。** 群組成員資格是登入當下決定的，執行完必須**完整登出再重新登入**這台機器（或至少開一個全新的終端機視窗執行 `newgrp docker`，但只對那個新視窗有效）。這是最常見卡關原因——指令跑了、卻感覺沒生效。

重新登入後再確認一次（不加 `sudo` 應該就能跑）：

```bash
docker ps
```

- 不加 `sudo` 不行、加 `sudo` 可以 → 群組還沒生效，再登出登入一次確認有沒有做對
- 兩者都不行 → daemon 沒啟動：`sudo systemctl start docker`

> **不要為了偷懶全程改用 `sudo docker ...` 繞過。** `sudo` 下的 `$HOME` 是 `/root`，之後 10GB 模型權重會被存到 `/root/.cache/huggingface`，跟一般帳號的環境分家，之後還得重抓一次、也容易搞混。

確認容器看得到 GPU（這行會順便拉容器映像，數 GB，需要一點時間）：

```bash
docker run --rm --gpus all nvcr.io/nvidia/vllm:26.06-py3 nvidia-smi
```

成功會印出 `nvidia-smi` 的 GPU 資訊表格（型號會顯示 `NVIDIA GB10`）。若失敗說找不到該標籤，到 [NGC vLLM 容器目錄](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm) 查目前可用版本，後續步驟改用：

```bash
DMAT_NGC_VLLM_TAG=nvcr.io/nvidia/vllm:<版本> ./scripts/setup-ocr.sh docker
```

---

## 步驟 2：準備模型下載權限（新機器要重新做一次）

Chandra OCR 2 的權重採 modified OpenRAIL-M 授權，換一台新機器代表本機沒有存過授權同意紀錄，需要重新處理：

1. 開 https://huggingface.co/datalab-to/chandra-ocr-2 ，若有授權同意鈕就按下去（換過帳號的話仍要按一次）
2. 建立一個 [Access Token](https://huggingface.co/settings/tokens)（read 權限即可，自己保管，不要外流）
3. 讓下載程序拿到 token：

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx
```

> 若步驟 3～4 下載時出現 `401` / `403`，就是漏了這步。
> 想長期保存可寫進 `~/.bashrc`，或改用 `hf auth login`。

---

## 步驟 3：執行安裝腳本

```bash
cd ~/Desktop/dmat-system-main
./scripts/setup-ocr.sh docker
```

腳本會自動做四件事：

1. 建立 Python 虛擬環境並安裝 AI 服務相依（含 Pillow 影像前處理）
2. 確認 docker 可用、映像已拉取、容器內看得到 GPU
3. 產生 `scripts/start-vllm-docker.sh`（推論伺服器啟動腳本）
4. 寫入 `src/ai-service/.env`，把引擎設成 `vision`

> `.env` 是本機設定檔，已列入 `.gitignore`，不會隨專案原始碼一起搬過來——**每台機器都要重新產生一次**，這是換機必經步驟，不是漏設定。

看到這行代表成功：

```
[ OK ] 已寫入 …/.env（DMAT_ENGINE=vision）
```

---

## 步驟 4：啟動推論伺服器

```bash
./scripts/start-vllm-docker.sh
```

**首次會下載約 10GB 模型權重，請耐心等**，存到 `~/.cache/huggingface`，之後重啟不必重抓。

就緒訊號——日誌出現這行：

```
INFO:     Application startup complete.
```

> 容器是背景常駐的（`-d --restart unless-stopped`）：關掉終端機不會停掉它、主機重開機會自動起來、崩潰也會自動重試。
> 腳本啟動後會接著跟隨日誌，按 **Ctrl+C 只是停止看日誌，不會停掉伺服器**。真的要停止：`docker stop dmat-vllm`。
> 之後想看日誌：`docker logs -f dmat-vllm`

另開一個終端機驗證推論伺服器活著：

```bash
curl --noproxy '*' http://localhost:8080/v1/models
```

### ⚠️ 實際遇到的錯誤 3：curl 連線被對方重設

```
curl: (56) Recv failure: 連線被對方重設
```

**這跟「連不上（Connection refused）」不一樣**——代表連線一度建立，但中途被切斷，通常是容器還在下載/載入模型、還沒真的把服務起起來（模型 10GB 下載或載入期間打這行本來就會失敗，不代表壞掉）。

**排查順序**：

1. 先看容器狀態：
   ```bash
   docker ps -a --filter name=dmat-vllm
   ```
   `STATUS` 是 `Up`（跑著，可能還在載入）、`Restarting`（一直重啟＝崩潰）、還是 `Exited`（掛了）。

2. 看日誌找原因：
   ```bash
   docker logs --tail 80 dmat-vllm
   ```
   留意：模型下載進度條、`Loading model...`、`CUDA out of memory`、`401/403`（token 沒生效）、或其他 Python traceback。

3. 或直接跑一鍵診斷，它會照 AI 服務(8100) → 推論伺服器(8080) → 容器 → 模型權重 這個順序自動判斷卡在哪：
   ```bash
   ./scripts/diagnose-ocr.sh
   ```

單純「還在下載/載入」的話，等它跑完就會恢復正常，不需要額外處理。

---

## 步驟 5：安裝 .NET 8 SDK（Web 應用需要，跟 OCR 引擎無關）

```bash
./start-dev.sh
```

### ⚠️ 實際遇到的錯誤 4：找不到 dotnet

```
[DMAT] 找不到 dotnet，請先安裝 .NET 8 SDK
```

**原因**：新機器是全新系統，沒有預裝 .NET 8 SDK；這是 Web 應用（`Dmat.Web`）本身的必要條件，跟 OCR 引擎裝不裝得起來無關，README 的「環境需求」裡也有列。

**解法（Ubuntu 24.04，含 aarch64）**：

```bash
sudo apt update
sudo apt install -y dotnet-sdk-8.0
```

裝完驗證：

```bash
dotnet --version
```

應顯示 `8.0.x`。

**若 apt 找不到 `dotnet-sdk-8.0` 套件**（部分精簡安裝的系統來源沒開），改用官方安裝腳本：

```bash
curl -sSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
chmod +x dotnet-install.sh
./dotnet-install.sh --channel 8.0

echo 'export DOTNET_ROOT=$HOME/.dotnet' >> ~/.bashrc
echo 'export PATH=$PATH:$HOME/.dotnet' >> ~/.bashrc
source ~/.bashrc
dotnet --version
```

裝好後回到專案目錄重新執行：

```bash
cd ~/Desktop/dmat-system-main
./start-dev.sh
```

---

## 步驟 6：確認啟動成功、找到手機連線網址

`start-dev.sh` 會依序：確認推論伺服器活著（沒起來會自動嘗試叫醒既有容器）→ 啟動 AI 服務（:8100）→ 啟動 Web 應用（綁 `0.0.0.0:5100`，同網段裝置都能連）。

啟動成功後，終端機會自動印出：

```
[DMAT] 啟動 Web 應用 → http://localhost:5100
[DMAT] 同網路裝置(手機)請連 → http://<這台機器的區網IP>:5100/Dashboard
[DMAT] 測試帳號：medic01 / leader01 / commander / admin   密碼：Dmat#2026
```

手機要跟這台 Spark 連同一個 Wi-Fi/區網，瀏覽器直接打上面那個網址即可，不需要另外設定。

若想自己先查這台機器的區網 IP：

```bash
hostname -I
```

啟動訊息應顯示 `引擎:vision`。**若仍顯示 `引擎:mock`**，代表 `src/ai-service/.env` 沒被讀到，回去檢查該檔案內容，或確認步驟 3 是否真的成功寫入。

---

## 步驟 7：驗證真的是真實引擎、把舊照片重跑一遍

```bash
curl --noproxy '*' http://localhost:8100/api/v1/health
```

要看到：

```json
{ "isMock": false, "engineReady": true, "engine": "datalab-to/chandra-ocr-2@http://localhost:8080（兩階段/chandra）" }
```

接著：

1. 瀏覽器開 http://localhost:5100 ，以 `medic01` / `Dmat#2026` 登入
2. 進「覆核佇列」，點任一筆
3. 按右上角「↻ 重新辨識」

原本的紅色「⚠ 本結果來自模擬引擎」警示應該消失，欄位換成照片的真實內容。

---

## 常見狀況總表（含上述換機過程實際遇到的）

| 症狀 | 原因 | 處理 |
|---|---|---|
| `拒絕不符權限的操作`（執行 .sh 腳本時） | 腳本遺失可執行權限（換機/搬檔常見） | `chmod +x start-dev.sh scripts/*.sh`，或用 `bash 腳本名稱` 執行 |
| `permission denied ... docker.sock` | 帳號未加入 `docker` 群組 | `sudo usermod -aG docker $USER`，**登出重新登入**才生效 |
| `curl: (56) Recv failure: 連線被對方重設` | 推論伺服器容器還在下載/載入模型，尚未就緒 | `docker ps -a --filter name=dmat-vllm` 看狀態、`docker logs --tail 80 dmat-vllm` 看進度，或跑 `./scripts/diagnose-ocr.sh` |
| `找不到 dotnet，請先安裝 .NET 8 SDK` | 新機器沒裝 .NET 8 SDK | `sudo apt install -y dotnet-sdk-8.0`，或用官方 `dotnet-install.sh` |
| 映像拉不到 / 找不到標籤 | NGC 版本標籤已更新 | 查 [NGC 目錄](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm) 後用 `DMAT_NGC_VLLM_TAG=…` 指定 |
| 模型下載 `401` / `403` | 沒接受 Hugging Face 授權或沒給 token | 回步驟 2，開網頁按同意 + 設定 `HF_TOKEN` |
| 容器內 `nvidia-smi` 看不到 GPU | NVIDIA Container Toolkit 未設定完成 | 檢查該工具是否隨新機系統映像一併安裝 |
| vLLM 說不支援模型架構 | 容器版本較舊，不認得該模型架構 | 改用備援模型（見下方） |
| 記憶體不足但容量明明夠 | DGX Spark 統一記憶體特性 | `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` |
| health 仍 `isMock: true` | `.env` 沒生效，或環境變數 `DMAT_ENGINE=mock` 蓋掉它（環境變數優先） | 檢查 `src/ai-service/.env`，或確認沒有殘留的 `DMAT_ENGINE` 環境變數 |
| `engineReady: false` | 推論伺服器沒起來或還在載入模型 | 同「Recv failure」的排查順序 |
| 連不上但埠明明開著 | 系統設了 `HTTP_PROXY` / `ALL_PROXY` | curl 測試一律加 `--noproxy '*'` |
| 手機連不到網址 | 手機跟 Spark 不在同一個 Wi-Fi/區網、或用了 `localhost` | 確認同網段，改用終端機印出的區網 IP 網址 |

### 備援模型（Chandra 跑不起來時）

程式碼不需修改，改用 NVIDIA 官方 DGX Spark 支援矩陣內已驗證的視覺模型：

編輯 `src/ai-service/.env`：
```
DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4
```

同時把 `scripts/start-vllm-docker.sh` 裡的 `MODEL=` 改成同一個值，兩邊都重啟。

### 想暫時切回模擬引擎（做介面測試時）

環境變數優先於 `.env`，不必改檔案：

```bash
DMAT_ENGINE=mock ./start-dev.sh
```

---

## 換機還原重點提醒

- `.env`、Hugging Face 授權同意、Access Token 都是**綁在單一機器上**的本機狀態，不會隨專案原始碼搬過來，換機一定要重新做步驟 2～3。
- 檔案可執行權限在搬移/還原過程容易遺失，先用 `chmod +x` 補回，可以省掉很多「怎麼權限不對」的困惑。
- Docker 群組權限**改完一定要登出重新登入**，不要在原本的終端機視窗裡繼續測試。
- 模型權重約 10GB，第一次啟動的下載時間屬正常現象，`curl` 連線被重設或逾時時先看 `docker logs`，不要急著重跑安裝腳本。
- 首次推論較慢（數十秒）是正常的，不代表卡住。

---

來源：本次 GB10 換機實際操作紀錄，參照專案文件 `README.md`、`docs/OCR安裝步驟.md`（`dmat-system-main`）。
