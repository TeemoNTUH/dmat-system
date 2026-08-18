# DMAT 災難醫療 AI 資訊整合與動態指揮暨決策輔助平台

DMAT 是一套將紙本傷患紀錄數位化的災難醫療資訊平台，支援：

> 拍攝紙本紀錄單 → AI OCR 與 NLP 結構化 → 人工覆核 → 傷患主檔 → 即時儀表板

本專案依《DMAT 系統架構書 v1.5》實作，包含 ASP.NET Core Web 應用程式與可替換的 Python AI 辨識服務。

## 功能概覽

- 紙本紀錄單影像上傳與影像去重
- OCR 轉寫及 77 個欄位的確定性結構化
- 人工覆核、修改與重新辨識
- 傷患主檔、檢傷紀錄及歷程保留
- SignalR 即時儀表板，並提供輪詢備援
- 角色與權限管理（醫護人員、站長、指揮官、系統管理者）
- AuditLog 稽核紀錄
- PWA 與離線上傳佇列
- OCR 引擎失效時降級為人工輸入

## 系統架構

```text
dmat-system/
├── src/
│   ├── Dmat.Web/              ASP.NET Core MVC (.NET 8) Web 應用程式
│   │   ├── Data/              EF Core DbContext 與種子資料
│   │   ├── Migrations/Sqlite/ SQLite 資料庫遷移
│   │   ├── Services/          影像、OCR、覆核、儀表板及稽核服務
│   │   └── wwwroot/           Bootstrap、PWA 與 SignalR 前端資產
│   └── ai-service/            Python FastAPI AI 辨識服務
│       ├── app/engines/       mock、vision、chandra_hf 推論引擎
│       ├── app/preprocess.py  EXIF 轉正、縮放與影像前處理
│       ├── app/structurer.py  OCR 文字至 77 個欄位的結構化
│       ├── tests/             單元測試與端到端測試
│       └── tools/try_image.py 單張影像診斷工具
├── docs/                      安裝與操作文件
├── scripts/                   OCR 設定及診斷腳本
├── DmatSystem.sln             .NET 解決方案
└── README.md
```

## 快速開始

### 環境需求

- Windows x64 開發環境
- .NET 8 SDK
- Python 3.10+
- Git
- （選用）NVIDIA GPU、Docker 與模型權重，用於真實 OCR 推論

### 1. 啟動 AI 辨識服務

預設使用 `mock` 引擎，不需要 GPU 或模型權重。

```powershell
cd src\ai-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

### 2. 啟動 Web 應用程式

另開一個 PowerShell 視窗：

```powershell
cd src\Dmat.Web
dotnet run
```

啟動後，依終端機顯示的網址開啟 Web 應用程式；預設通常為 `http://localhost:5100`。

### 開發用模擬帳號

以下帳號僅供開發與演練使用，正式導入前請立即更換密碼與帳號設定。

| 帳號 | 角色 | 預設密碼 |
|---|---|---|
| `medic01`～`medic03` | 醫護人員 | `Dmat#2026` |
| `leader01` | 站長 | `Dmat#2026` |
| `commander` | 指揮官 | `Dmat#2026` |
| `admin` | 系統管理者 | `Dmat#2026` |

## OCR 引擎

### Mock 引擎

Mock 引擎是預設設定，固定回傳台大版樣張的模擬資料，不會辨識實際上傳的照片。若覆核畫面出現與照片不符的「陳○宏」資料，通常就是因為仍在使用 Mock 引擎。

確認 AI 服務狀態：

```powershell
curl.exe --noproxy "*" http://localhost:8100/api/v1/health
```

請確認回應中的 `isMock` 欄位。

### Chandra OCR 2

切換真實 OCR 引擎前，請先閱讀 [OCR 安裝步驟](docs/OCR安裝步驟.md) 與 [AI 服務使用說明](docs/AI服務使用說明.md)。

```bash
./scripts/setup-ocr.sh          # 偵測環境並提供建議
./scripts/setup-ocr.sh docker   # NVIDIA 官方 NGC 容器
./scripts/setup-ocr.sh hf       # transformers 本機推論
./scripts/setup-ocr.sh vllm     # 安裝 vLLM（非 GB10 平台）
```

GB10 / DGX Spark 為 aarch64 + Blackwell（SM121）平台，PyPI 上的 vLLM wheel 通常不相容，因此建議優先使用 NVIDIA 官方容器：

```bash
./scripts/setup-ocr.sh docker
./scripts/start-vllm-docker.sh
./start-dev.sh
```

首次啟動容器可能需要下載約 10 GB 的模型權重。設定腳本會寫入 `src/ai-service/.env`；這些本機設定檔已列入 `.gitignore`，請勿提交至公開 repository。

真實引擎採兩階段流程：

1. OCR 引擎將影像轉寫為保留版面的 HTML，包含勾選框狀態。
2. `app/structurer.py` 使用可追溯的確定性規則對應至 77 個欄位。

若容器不支援 `chandra-ocr-2`，可改用 NVIDIA Spark 支援矩陣中的視覺模型，例如：

```text
DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4
```

## 診斷與測試

逐段檢查 AI 服務、推論伺服器、容器與模型權重：

```bash
./scripts/diagnose-ocr.sh
```

診斷單張影像：

```bash
cd src/ai-service
.venv/bin/python tools/try_image.py <影像路徑>
.venv/bin/python tools/try_image.py <影像路徑> --raw
```

在 Windows PowerShell 中，也可以使用：

```powershell
python tools\try_image.py <影像路徑>
python tools\try_image.py <影像路徑> --raw
```

不需要 GPU 或模型權重即可執行測試：

```bash
cd src/ai-service
python -m pytest tests
```

常見判斷方式：

- OCR 轉寫為空：可能是影像方向、亮度或推論模型設定問題。
- OCR 有內容但欄位為空：請檢查 `app/structurer.py` 的結構化規則。
- 上傳不同照片卻得到相同結果：請先確認是否仍使用 Mock 引擎。

## 相關文件

- [OCR 安裝步驟](docs/OCR安裝步驟.md)：真實 OCR 引擎安裝與平台注意事項
- [Web 應用使用說明](docs/Web應用使用說明.md)：角色操作、資料備份與疑難排解
- [AI 服務使用說明](docs/AI服務使用說明.md)：引擎切換、REST API 與辨識品質調整
- [操作流程圖](docs/操作流程圖.mermaid)：系統操作流程

## 設計與架構對照

- 欄位對照以 `Field_Map` 為單一事實來源。
- `Ocr:FieldThresholds` 可針對不同欄位設定信心門檻。
- 影像使用 SHA-256 進行去重與完整性驗證。
- 身分證字號使用 Data Protection 加密，並以遮罩方式顯示。
- `AuditLog` 採僅新增、查詢的設計。
- 傷票編號重複時視為同一傷患的複檢或補頁，並保留檢傷歷程。
- 中央同步、SQL Server provider 與多語系資源目前為預留功能。

## 已知限制

- 目前僅處理紀錄單第 1 頁（共 8 頁）。
- 後送調度、系統管理後台與跨站彙整尚未實作。
- 開發環境使用 HTTP；正式部署前應依架構書設定內部 CA 憑證與 HTTPS。
- 本專案不應存放真實病患資料於公開 repository。

## 授權

專案程式碼採 MIT License。`datalab-to/chandra-ocr-2` 模型權重則依其 modified OpenRAIL-M 授權；研究、個人及小型新創用途以外的商業使用，請先確認模型授權條款。
