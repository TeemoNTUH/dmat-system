# DMAT 轉移部署與重建環境

適用情境：把 DMAT 從目前的主機搬到另一台電腦（換機、增設站點、災後重建），或在同一台機器上把環境整個重裝。

> 只需要處理 OCR 推論引擎（GB10 / Docker / vLLM）時，請直接看 [DMAT-GB10換機還原教學](DMAT-GB10換機還原教學.md)。本文件涵蓋整體流程：程式碼、資料、環境三部分怎麼搬、搬到哪裡。

---

## 0. 先搞清楚：要搬的東西分成三類

| 類別 | 內容 | 怎麼搬 | 進 GitHub？ |
|---|---|---|---|
| **程式碼** | `src/`、`scripts/`、`docs/`、`start-dev.sh`、`DmatSystem.sln` | `git push` → 新機 `git clone` | ✅ |
| **執行期資料** | `src/Dmat.Web/app_data/` 內的 `dmat.db`（資料庫）、`keys/`（身分證字號加密金鑰）、`images/`（紀錄單照片） | `scripts/backup-data.sh` 打包成 zip → 加密 → 雲端硬碟 | ❌ 絕對不可 |
| **本機環境** | .NET 8 SDK、Python 虛擬環境 `.venv`、`src/ai-service/.env`、Docker 容器與模型權重、桌面啟動器（由範本產生） | 每台機器重新建立 | ❌ |

> ⚠️ **資料庫與金鑰必須成對保存。** 身分證字號以 `app_data/keys/` 內的 Data Protection 金鑰加密；只還原 `dmat.db` 而沒有對應金鑰，既有傷患的身分證字號將**永久無法解密**。

以下不需要搬，新機器會自動重建：`bin/`、`obj/`、`.venv/`、`__pycache__/`、`logs/`（日誌，需要留存時另行歸檔）。

---

## 1. 舊機器：打包

### 1.1 程式碼簽入 GitHub

```bash
cd <專案目錄>
git status                 # 確認只有預期中的程式碼變更
git add -A
git status                 # 再看一次：不應出現 app_data/、backups/、.env、*.db、*.jpg
git commit -m "<說明>"
git push origin main
```

`.gitignore` 已排除 `app_data/`、`backups/`、`logs/`、`.env`、`.venv/` 等；`git add -A` 後若仍看到上述任何一項，**先停下來檢查 `.gitignore`**，不要提交。

### 1.2 備份資料庫與照片

**Linux / macOS**（服務執行中也可以備份，會取得一致的快照）：

```bash
./scripts/backup-data.sh               # 輸出到 ./backups/
./scripts/backup-data.sh /media/usb    # 或指定輸出資料夾
```

產出 `backups/dmat-backup-YYYYMMDD-HHMMSS.zip`，內容：

```text
app_data/dmat.db          資料庫快照（已做 integrity_check）
app_data/keys/*.xml       身分證字號加密金鑰
app_data/images/YYYYMM/   紀錄單照片（檔名即 SHA-256）
config/ai-service.env     舊機的 OCR 引擎設定（僅供參考）
MANIFEST.txt              各資料表筆數、每個檔案的 SHA-256
RESTORE.txt               簡易還原說明
```

終端機最後會印出整個 zip 的 SHA-256，請一併記下來，供下載後驗證。

**Windows**（沒有 bash 時）：先**停止 DMAT**（關掉 `dotnet run` 的視窗），再於 PowerShell 執行：

```powershell
cd <專案目錄>
New-Item -ItemType Directory -Force backups | Out-Null
Compress-Archive -Path src\Dmat.Web\app_data -DestinationPath "backups\dmat-backup-$(Get-Date -Format yyyyMMdd-HHmmss).zip"
```

> Windows 版是直接壓整個資料夾，**一定要先停服務**：SQLite 為 WAL 模式，執行中直接複製可能漏掉尚未寫回主檔的資料。

### 1.3 加密後再上傳雲端硬碟

備份檔含病患個資**與**解密金鑰，拿到 zip 的人就能讀到所有內容。上傳前請：

1. 確認雲端硬碟是院內核可、可存放個資的空間。
2. 以 AES-256 加密（密碼另以其他管道交付，不要和檔案放一起）：

```bash
# Linux：sudo apt install -y p7zip-full
7z a -mhe=on -p dmat-backup-YYYYMMDD-HHMMSS.7z backups/dmat-backup-YYYYMMDD-HHMMSS.zip
```

Windows 可用 7-Zip 圖形介面：右鍵 →「加入壓縮檔」→ 加密方式選 **AES-256**，並勾選「加密檔名」。

3. 上傳完成後，視院內規範決定是否刪除本機 `backups/` 內的明文 zip。

### 1.4 打包檢查清單

- [ ] `git push` 成功，GitHub 上看得到最新 commit
- [ ] 備份 zip 已產生，終端機顯示「完整性 ok」，影像數與實際相符
- [ ] 已記下 zip 的 SHA-256
- [ ] 已加密並上傳到核可的雲端位置
- [ ] 已記錄舊機 `.env` 用的引擎與模型（備份內 `config/ai-service.env` 也有）

---

## 2. 新機器：安裝基本環境

### Ubuntu 24.04（x64 或 aarch64 / GB10 皆適用）

```bash
sudo apt update
sudo apt install -y git curl unzip python3 python3-venv python3-pip dotnet-sdk-8.0
dotnet --version     # 應為 8.0.x
python3 --version    # 應 ≥ 3.10
```

`apt` 找不到 `dotnet-sdk-8.0` 時，改用官方安裝腳本，見 [GB10 換機還原教學](DMAT-GB10換機還原教學.md) 步驟 5。

### Windows 10 / 11

```powershell
winget install Git.Git Microsoft.DotNet.SDK.8 Python.Python.3.12
```

裝完請**重新開一個 PowerShell 視窗**，讓 PATH 生效。

---

## 3. 取得程式碼

```bash
cd ~/Code
git clone https://github.com/TeemoNTUH/dmat-system.git
cd dmat-system
chmod +x start-dev.sh scripts/*.sh      # Linux：補回可執行權限
```

---

## 4. 還原資料

> 全新部署、不需要舊資料時，**跳過本節**：第一次啟動會自動建立空白資料庫、金鑰與預設帳號。

1. 從雲端下載備份，先驗證完整性，再解密：

```bash
sha256sum dmat-backup-YYYYMMDD-HHMMSS.zip   # 與打包時記下的值比對（解密後的 zip）
```

2. **確認 DMAT 沒有在執行**，再解壓到 `src/Dmat.Web/`：

```bash
unzip dmat-backup-YYYYMMDD-HHMMSS.zip 'app_data/*' -d src/Dmat.Web/
chmod -R go-rwx src/Dmat.Web/app_data      # 僅限本帳號讀寫
```

Windows：解壓後將 `app_data` 資料夾整個放進 `src\Dmat.Web\`。

若目標位置已經有 `app_data/`（例如曾經先啟動過一次），請先改名保留（如 `app_data.old`），**不要和備份混在一起**：新產生的金鑰與舊資料庫不相容。

3. 抽查還原內容與 `MANIFEST.txt` 一致：

```bash
python3 - <<'PY'
import sqlite3
c = sqlite3.connect("src/Dmat.Web/app_data/dmat.db")
print(c.execute("pragma integrity_check").fetchone()[0])
for t in ("Patients", "RecordImages", "TriageRecords", "AuditLogs"):
    print(t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
PY
find src/Dmat.Web/app_data/images -name '*.jpg' | wc -l
```

---

## 5. 設定 OCR 引擎

`src/ai-service/.env` 不在 git 也不在備份還原範圍內，**每台機器都要重新產生**。

| 情境 | 做法 |
|---|---|
| 只做介面測試／演練、沒有 GPU | 什麼都不用做，預設為 `mock` 模擬引擎（結果固定為樣張假資料） |
| GB10 / DGX Spark | 依 [GB10 換機還原教學](DMAT-GB10換機還原教學.md) 步驟 1～4：`./scripts/setup-ocr.sh docker` → `./scripts/start-vllm-docker.sh` |
| 其他 NVIDIA GPU 主機 | 依 [OCR 安裝步驟](OCR安裝步驟.md)：`./scripts/setup-ocr.sh` 會偵測平台並建議模式 |

需要沿用舊機的調整值（例如 `DMAT_VISION_TIMEOUT_S`、`DMAT_VERIFY=0`）時，參考備份內 `config/ai-service.env`，在 `setup-ocr.sh` 產生新的 `.env` 後手動補上。**不要直接覆蓋**：推論端點與模型路徑可能因機器而異。

---

## 6. 啟動與驗證

```bash
./start-dev.sh
```

Windows 沒有 bash 時，依 [README「快速開始」](../README.md#快速開始) 分兩個 PowerShell 視窗啟動 AI 服務與 Web 應用。

驗證清單：

- [ ] 瀏覽器自動開啟 `http://localhost:5100`，能以 `admin` 登入
- [ ] `curl --noproxy '*' http://localhost:8100/api/v1/health` 的 `isMock` 與預期一致（真實引擎應為 `false`）
- [ ] 儀表板的傷患人數與 `MANIFEST.txt` 的 `Patients` 筆數一致（有還原資料時）
- [ ] 隨機開 2～3 位傷患明細：紀錄單影像正常顯示（不是「⚠ 影像檔遺失」），身分證字號正常顯示（沒有解密錯誤）
- [ ] 手機連 `http://<新機區網IP>:5100/Dashboard` 可開啟（防火牆需放行 5100 埠）
- [ ] 上傳一張測試照片，確認能進覆核佇列；測完刪除

> 正式導入前，請更換 README 所列的預設帳號密碼（`Dmat#2026`）。

---

## 7. 桌面啟動器（Linux）

repo 只保存不含本機路徑的範本 `scripts/start-dmat.desktop.in`，實際的啟動器要在每台機器上產生：

```bash
cd <專案目錄>
./scripts/install-desktop-launcher.sh
```

腳本會把範本中的 `@DMAT_ROOT@` 換成專案的實際位置，安裝到「桌面」與應用程式選單（活動總覽搜尋「DMAT」），並在 GNOME 標記為受信任。**換機或搬移專案資料夾後，重新執行一次即可。**

- 只想裝到特定位置：`./scripts/install-desktop-launcher.sh ~/Desktop`
- 第一次點擊若出現「不受信任的啟動器」，右鍵 →「允許啟動」
- 啟動器以 `bash start-dev.sh` 執行，即使搬移時遺失可執行權限也能啟動
- 產生出來的 `.desktop` 含本機絕對路徑（會透露帳號名稱），**不要複製回 repo 提交**

---

## 8. 常見問題

| 症狀 | 原因 | 處理 |
|---|---|---|
| 傷患明細出現解密錯誤，或日誌出現 `CryptographicException` / `The key ... was not found in the key ring` | 資料庫與 `app_data/keys/` 不是同一份備份，或新機啟動後產生了新金鑰 | 停服務 → 刪除（或改名）新產生的 `app_data/` → 重新解壓**同一份**備份 |
| 傷患明細顯示「⚠ 影像檔遺失」 | `app_data/images/` 沒有一起還原，或解壓到錯誤層級（變成 `app_data/app_data/`） | 確認路徑為 `src/Dmat.Web/app_data/images/YYYYMM/*.jpg` |
| 啟動時 `database is locked` | 還原時服務仍在執行，或殘留舊的 `dmat.db-wal` / `dmat.db-shm` | 停服務，刪除不屬於本次備份的 `-wal` / `-shm` 檔後重啟 |
| 登入時帳號密碼錯誤 | 未還原資料時是全新資料庫，只有預設帳號；還原後則沿用舊機的帳號密碼 | 依實際情況使用對應帳號 |
| `拒絕不符權限的操作`（執行 .sh） | 搬移過程遺失可執行權限 | `chmod +x start-dev.sh scripts/*.sh` |
| `位址已在使用中`（5100 / 8100） | 前一次啟動未完全關閉 | `ss -ltnp \| grep -E '5100\|8100'` 找出行程後結束 |
| 覆核結果都是「陳○宏」 | 仍使用 mock 引擎，`.env` 未產生或未生效 | 回第 5 節 |

---

## 附錄：絕對不可提交到 GitHub 的檔案

| 路徑 | 原因 |
|---|---|
| `src/Dmat.Web/app_data/` | 病患資料、紀錄單照片、加密金鑰 |
| `backups/` | 同上的打包檔 |
| `src/Dmat.Web/logs/` | 日誌可能含辨識內容與操作紀錄 |
| `src/ai-service/.env`、`.env.bak` | 各站本機設定 |
| 產生後的 `start-dmat.desktop` | 含本機絕對路徑與帳號名稱；repo 只放範本 `scripts/start-dmat.desktop.in` |
| Hugging Face Access Token（`HF_TOKEN`） | 個人憑證，只放在環境變數或 `~/.cache/huggingface` |

以上皆已列入 `.gitignore`；新增任何資料輸出位置時，請同步更新 `.gitignore`。
