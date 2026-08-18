# DMAT 災難醫療 AI 資訊整合與動態指揮暨決策輔助智慧平台

依《DMAT 系統架構書 v1.5》實作:
**拍攝紙本紀錄單 → AI 辨識(OCR+NLP 結構化)→ 人工覆核 → 傷患主檔 → 即時儀表板**。

## 專案結構

```
dmat-system/
├── src/Dmat.Web/          ASP.NET Core MVC(.NET 8)+ SignalR + Identity + EF Core 8(SQLite)
│   ├── Data/              DbContext、種子資料(角色/模擬帳號/診斷代碼)
│   ├── Migrations/Sqlite/ SQLite migrations(SqlServer 依架構書 6.3.1 預留)
│   ├── Services/          影像入庫、OCR 客戶端、覆核、儀表板、稽核
│   └── wwwroot/           Bootstrap 5 本地資產、PWA(manifest/sw.js/IndexedDB 離線佇列)
└── src/ai-service/        Python FastAPI AI 辨識服務(架構書 5.2 REST 介面)
    ├── app/engines/       推論引擎抽象:mock(預設)/ vision(OpenAI 相容端點)/ chandra_hf(本機推論)
    ├── app/preprocess.py  影像前處理(EXIF 轉正、長邊縮放、對比增強)
    ├── app/structurer.py  NLP 結構化:OCR 轉寫 → 77 欄位(規則式,可稽核)
    ├── tests/             結構化與端到端測試(不需 GPU/模型)
    └── tools/try_image.py 單張診斷工具
```

## 使用說明

- [docs/OCR安裝步驟.md](docs/OCR安裝步驟.md) — **把模擬引擎換成真實 OCR 的逐步安裝指引(GB10/DGX Spark)**
- [docs/Web應用使用說明.md](docs/Web應用使用說明.md) — 醫護/站長/指揮官操作流程、資料備份、疑難排解
- [docs/AI服務使用說明.md](docs/AI服務使用說明.md) — 引擎切換、REST API、辨識品質調整

## 快速啟動(開發環境:Windows x64)

```bash
# 1. AI 辨識服務(預設 mock 引擎,回傳台大版樣張辨識結果)
cd src/ai-service
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100

# 2. Web 應用(http://localhost:5100)
cd src/Dmat.Web
dotnet run
```

### 模擬任務帳號(開發/演練用;正式導入請更換)

| 帳號 | 角色 | 密碼 |
|---|---|---|
| medic01~03 | 醫護人員 | `Dmat#2026` |
| leader01 | 站長 | `Dmat#2026` |
| commander | 指揮官 | `Dmat#2026` |
| admin | 系統管理者 | `Dmat#2026` |

### ⚠ 預設引擎是模擬的,不會辨識你的照片

`mock` 引擎固定回傳台大版樣張(陳○宏)的假資料,**不論上傳哪張影像都一樣**。
若覆核畫面出現「陳○宏」而你拍的不是那張樣張,就是這個原因。

```bash
curl --noproxy '*' http://localhost:8100/api/v1/health   # 看 "isMock"
```

### 切換 Chandra OCR 2 真實推論

```bash
./scripts/setup-ocr.sh          # 偵測環境(含 GB10/SM121)並給建議
./scripts/setup-ocr.sh docker   # NVIDIA 官方 NGC 容器 ← GB10 / DGX Spark 首選
./scripts/setup-ocr.sh hf       # 本機 transformers 推論,不另跑伺服器
./scripts/setup-ocr.sh vllm     # pip 安裝 vLLM(非 GB10 平台)
```

GB10 為 aarch64 + Blackwell(SM121):PyPI 的 vLLM wheel 多半不支援,自行建置需要
LLVM/Triton 的 ARM64 patch。**官方容器已預先建置好,可繞過這兩個問題**,故列為首選。

```bash
./scripts/setup-ocr.sh docker
./scripts/start-vllm-docker.sh   # 終端機 A:首次下載約 10GB 權重
./start-dev.sh                    # 終端機 B
```

腳本會寫入 `src/ai-service/.env`,`start-dev.sh` 啟動時會顯示目前引擎並在使用
模擬引擎時警示。已上傳的照片不需重拍 —— 覆核頁按「**↻ 重新辨識**」即可用新引擎重跑。

若容器版本不認得 `chandra-ocr-2` 的架構,可改用 NVIDIA 官方 Spark 支援矩陣內
已驗證的視覺模型作為備援,**程式端不需修改**(服務會自動改用通用轉寫提示):
`DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4`

真實引擎預設走兩階段(架構書 5.1「OCR + NLP 結構化」):
Chandra 以原生訓練提示轉寫為保留版面的 HTML(含勾選框狀態),
再由 `app/structurer.py` 以確定性規則對應到 77 欄位 —— 每欄都能追溯是從哪段文字抓到的。

引擎抽換不影響 Web 應用之 REST 介面(架構書 5.4)。
GB10 為 aarch64 + SM121,標準 vLLM wheel 多半不支援,且不可直接 `pip install torch`;
詳見 [docs/AI服務使用說明.md](docs/AI服務使用說明.md) 第 2.2 節。

> 模型權重 `datalab-to/chandra-ocr-2` 為 modified OpenRAIL-M(研究/個人/小型新創免費,
> 其他商業用途需另洽授權),與下方「開源授權尚未定案」一併確認。

### 診斷

```bash
./scripts/diagnose-ocr.sh     # 逐段檢查 AI 服務 → 推論伺服器 → 容器 → 模型權重,並給判定
```

照片為什麼讀不出來:

```bash
cd src/ai-service
.venv/bin/python tools/try_image.py <照片路徑>          # 引擎、前處理、辨識到幾欄
.venv/bin/python tools/try_image.py <照片路徑> --raw    # 一併印出 OCR 原始轉寫

# 測試(不需 GPU 或模型權重,以假端點取代 vLLM)
python tests/test_structurer.py && python tests/test_pipeline.py && python tests/test_engine_switch.py
```

轉寫是空的 → OCR 沒讀到(方向錯、太暗、mmproj 沒掛);
轉寫有內容但欄位空 → 結構化字典沒對上,調 `app/structurer.py`。

## 設計對照(架構書章節)

- 欄位對照單一事實來源:`20260712初版簡報/damt_db_fields.xlsx` Field_Map(附錄 B.2)
- 信心門檻:appsettings `Ocr:FieldThresholds` 分欄位設定,必填欄位較嚴(4.1)
- SHA-256 影像去重與完整性(7.4.2/8.3);身分證字號 Data Protection 加密+遮罩顯示(8.3)
- AI 失效降級人工輸入(5.3);儀表板 SignalR+輪詢備援(4.2);AuditLog 僅增查(8.4)
- 傷票編號重複時視為同一傷患之複檢/補頁,新增檢傷紀錄保留歷程(附錄 B.3)
- 【預留】中央同步(SyncLog,7.6)、SqlServer provider(6.3)、i18n(Resources)

## 已知範圍限制

- 僅處理紀錄單頁 1/8;後送調度、系統管理後台、跨站彙整未實作
- 開發階段以 HTTP 運行;正式部署依架構書 8.3 以內部 CA 憑證啟用 HTTPS
- 開源授權MIT
