# DMAT AI 辨識服務使用說明

適用對象:系統管理者、維運人員、開發人員。
本服務為獨立部署的服務程序(架構書 5.1),提供 OCR、NLP 欄位結構化與資料合理性檢核;
Web 應用透過內部 REST API 呼叫,兩者鬆耦合,模型與推論引擎可獨立抽換。

---

## 0. 最重要的一件事:預設是「模擬引擎」

**預設的 `mock` 引擎不會看你的照片。** 它固定回傳台大版樣張(陳○宏 / A125680363)的
一組寫死資料,不論上傳哪一張影像都一樣。這是為了讓介面能在沒有 GPU 的機器上開發。

如果你在覆核畫面看到「陳○宏」但拍的不是那張樣張,問題就在這裡,不是 OCR 壞了。

判斷方法:

```bash
curl --noproxy '*' http://localhost:8100/api/v1/health
# "isMock": true  → 模擬引擎,結果是假資料
# "isMock": false → 真實引擎
```

切換為真實辨識:

```bash
./scripts/setup-ocr.sh          # 偵測環境並給建議(會判斷是否為 GB10)
./scripts/setup-ocr.sh docker   # NVIDIA 官方 NGC 容器 ← GB10 / DGX Spark 首選
./scripts/setup-ocr.sh hf       # 本機 transformers,不另跑伺服器
./scripts/setup-ocr.sh vllm     # pip 安裝 vLLM(非 GB10 平台)
```

腳本會產生 `src/ai-service/.env`,服務啟動時自動讀取,`start-dev.sh` 也會顯示目前引擎。
既有已上傳的照片不必重拍 —— 到覆核頁按「**↻ 重新辨識**」即可用新引擎重跑。

---

## 1. 啟動

```bash
cd src/ai-service
pip install -r requirements.txt          # 首次
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

啟動後可開 http://localhost:8100/docs 檢視互動式 API 文件(Swagger UI)。

> 埠號 8100 與 Web 應用的 `appsettings.json → AiService:BaseUrl` 對應,兩邊要一致。

---

## 2. 推論引擎

以環境變數 `DMAT_ENGINE` 切換,**REST 介面完全相同**,Web 應用不需任何修改(架構書 5.4)。

| 引擎 | 說明 | 需要什麼 |
|---|---|---|
| `mock` | 模擬。回傳寫死樣張資料,**與影像無關** | 無 |
| `vision` | 呼叫任何 OpenAI 相容視覺端點 | 另跑 vLLM / SGLang / llama.cpp / Ollama |
| `chandra` | `vision` 的別名(架構書 5.4 稱法) | 同上 |
| `chandra_hf` | 本機 transformers 直接載入模型 | torch + transformers,無需另跑伺服器 |

### 2.1 兩階段辨識(預設)

真實引擎預設走兩階段,對應架構書 5.1 的「OCR + NLP 結構化」:

1. **轉寫** — 以 Chandra 的原生訓練提示,把整張表單轉為保留版面的 HTML,
   勾選框輸出成 `<input type="checkbox" checked>`。
2. **結構化** — `app/structurer.py` 以確定性規則把 HTML 對應到 77 個欄位。

為什麼第二階段不再叫一次 LLM:Chandra 這類 OCR 專用模型的強項是忠實轉寫,
並不擅長照自訂 schema 填 JSON。而「1.2 醫療記錄單」格式固定、44 項診斷名稱都是已知常數,
用規則對應更準、更快,而且每個欄位都能說出是從哪段文字抓到的(架構書 8.4 責任追溯)。

3. **針對性複查**(`app/verify.py`)— 只在偵測到不確定時觸發。

要改回單階段(直接要模型吐 JSON,適合通用 VLM 如 Qwen-VL):`DMAT_TWO_STAGE=0`。

#### 第三階段:針對性複查

整頁轉寫時模型要同時處理上百個元素,注意力被攤薄,於是出現三種典型錯誤:
勾記號畫超出格線導致隔壁格也被判成勾選、單選的檢傷分類被勾成兩個、
密集表格裡的手寫傷票編號被略過。

但只問一個聚焦問題時(「這一列裡**哪一個方框內**有勾選記號?」),模型準確得多。
因此偵測到下列情形時,會帶著**同一張影像**回頭問模型:

| 順序 | 觸發條件 | 問法 |
|---|---|---|
| 1 | 檢傷分類缺漏、信心不足、或多格同時勾選 | 單選題,只能答 1/2/3/4/4-1 |
| 2 | 傷票編號(必填)缺漏或格式可疑 | 只讀該格手寫文字 |
| 3 | 診斷群組有相鄰同時勾選 | 複選題,答項次數字 |
| 4 | 身分證字號、姓名讀到了但不合格式 | 只讀該格,並在提示中給出格式 |

順序即優先序 —— 診斷牽涉臨床處置,排在選填欄位之前。

**選填欄位若整格空白就不複查**:那很可能本來就沒填,問一次要花數十秒。
只有「讀到了東西但不合格式」才值得再問,例如身分證字號讀成 9 碼數字 ——
格式固定是「1 個英文字母 + 9 個數字」,少一碼必定是漏了開頭那個字母
(手寫字母貼著格線時很常見),提示詞會直接請模型回頭找那個字母。

提示詞明確要求:**勾選記號跨在兩格之間時,只算記號主體所在的那一格**。

安全性設計:複查答案一樣要通過 `field_spec` 驗證才會採用;答 `UNKNOWN`/`NONE`
或不合規時保留第一輪結果,絕不會因為複查而讓資料變差。任何一題失敗只跳過該題。

代價是每題多一輪推論(數十秒)。以 `DMAT_VERIFY_MAX_TASKS` 設上限,
現場若要優先追求速度可用 `DMAT_VERIFY=0` 關閉。

### 2.2 GB10 / DGX Spark(aarch64)— 建議路徑

本專案的目標平台 GB10 是 **aarch64 + Blackwell(SM121)**,128GB 統一記憶體放得下
BF16 的 5B 模型(約 10GB),不需量化。但有兩個已知地雷:

- **PyPI 的標準 vLLM wheel 多半不支援 SM121**(`SM_121a architecture not recognized`);
  自行從原始碼建置需要 LLVM/Triton 的 ARM64 patch。
- **不要直接 `pip install torch`**:aarch64 會裝到 CPU 版。

因此**首選 NVIDIA 官方容器** —— 已為 ARM64 + Blackwell 預先建置,兩個地雷都繞過:

```bash
./scripts/setup-ocr.sh docker      # 檢查 docker/GPU、拉映像、產生啟動腳本、寫入 .env

./scripts/start-vllm-docker.sh     # 終端機 A:啟動推論伺服器(首次下載約 10GB 權重)
                                    # 看到 "Application startup complete" 即就緒
./start-dev.sh                      # 終端機 B

curl --noproxy '*' http://localhost:8100/api/v1/health   # 確認 "isMock": false
```

容器版本可用 `DMAT_NGC_VLLM_TAG` 指定(預設 `nvcr.io/nvidia/vllm:26.06-py3`),
最新版見 [NGC vLLM 容器目錄](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm)。

**備援模型**:若容器版本較舊、vLLM 不認得 `chandra-ocr-2` 的模型架構(`qwen3_5`),
改用 NVIDIA 官方 Spark 支援矩陣內已驗證的視覺模型,**程式端不需修改**:

```bash
DMAT_VISION_MODEL=nvidia/Qwen2.5-VL-7B-Instruct-NVFP4
```

服務會自動偵測「非 Chandra 模型」並改用中文指示式轉寫提示(見 §2.5)。
辨識品質會低於 Chandra(OCR 專用 vs 通用 VLM),但可先讓整條流程跑起來。

**UMA 注意事項**:DGX Spark 為統一記憶體架構,若出現記憶體不足但實際容量足夠,
手動清一下 buffer cache:

```bash
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
```

**不想用 Docker**:先依 NVIDIA 官方指引裝好 aarch64 + CUDA 版 torch,再:

```bash
./scripts/setup-ocr.sh hf
./start-dev.sh
```

模型於服務啟動後於背景載入(數十秒),`/api/v1/health` 的 `engineReady` 轉 true 即可用。

### 2.3 llama.cpp(GGUF 量化;Mac / CPU / 一般 GPU)

```bash
llama-server -m chandra-ocr-2-Q4_K_M.gguf --mmproj mmproj-F16.gguf --port 8080
```

`--mmproj`(視覺投影檔)**必掛**,否則模型看不到影像、只會回空白轉寫。

然後 `DMAT_ENGINE=vision DMAT_VISION_BASE_URL=http://localhost:8080`。

### 2.4 環境變數一覽

設定可寫進 `src/ai-service/.env`(服務啟動時自動載入),或直接用環境變數覆寫
(環境變數優先,方便臨時 `DMAT_ENGINE=mock` 切回去做介面測試)。
設定檔位置可用 `DMAT_ENV_FILE` 指向集中管理路徑(如 `/etc/dmat/engine.env`)。

| 變數 | 預設 | 說明 |
|---|---|---|
| `DMAT_ENGINE` | `mock` | `mock` / `vision` / `chandra` / `chandra_hf` |
| `DMAT_ENV_FILE` | `src/ai-service/.env` | 引擎設定檔位置 |
| `DMAT_TWO_STAGE` | `1` | 1=轉寫後規則結構化;0=直接要模型輸出 JSON |
| `DMAT_PROMPT_STYLE` | `auto` | `auto` / `chandra` / `generic`(見 §2.5) |
| `DMAT_VERIFY` | `1` | 第三階段針對性複查。關閉可省下數十秒,但勾選溢出與缺漏編號就只能靠人工覆核 |
| `DMAT_VERIFY_MAX_TASKS` | `4` | 單張最多複查幾題(每題一輪推論) |
| `DMAT_NGC_VLLM_TAG` | `nvcr.io/nvidia/vllm:26.06-py3` | 官方容器版本(僅 setup 腳本使用) |
| `DMAT_VISION_BASE_URL` | `http://localhost:8080` | OpenAI 相容端點(vLLM/llama.cpp/SGLang/Ollama) |
| `DMAT_VISION_MODEL` | `datalab-to/chandra-ocr-2` | 傳給端點的 model 名稱 |
| `DMAT_VISION_API_KEY` | (空) | 端點需要金鑰時填 |
| `DMAT_VISION_TIMEOUT_S` | `300` | 單張推論逾時秒數 |
| `DMAT_VISION_MAX_TOKENS` | `8192` | 轉寫輸出上限;整頁表單建議 ≥8192 |
| `DMAT_HF_MODEL_ID` | `datalab-to/chandra-ocr-2` | 本機推論模型 |
| `DMAT_HF_DTYPE` | `bfloat16` | GB10 用 bfloat16 |
| `DMAT_PREPROCESS` | `1` | 影像前處理總開關 |
| `DMAT_PREPROCESS_MAX_EDGE` | `2000` | 長邊縮放上限。太大會拖慢推論且稀釋注意力 |
| `DMAT_PREPROCESS_ENHANCE` | `0` | 自動對比+銳化。淺色手寫、光線不均時開啟 |
| `DMAT_RETURN_RAW` | `0` | analyze 一併回傳模型原始轉寫(**含個資,正式環境勿開**) |

模型檔應於**裝置整備階段預先下載**,現場推論完全離線,不需對外網路。

> **授權提醒**:`datalab-to/chandra-ocr-2` 權重為 modified OpenRAIL-M —— 研究、個人、
> 年營收/募資未達 200 萬美元之新創可免費使用,其他商業用途需另洽 Datalab 授權。
> 程式碼本身為 Apache 2.0。README 已列「開源授權尚未定案」,正式發布前請一併確認此項。

### 2.5 轉寫提示風格

第一階段的提示要配合模型:

| `DMAT_PROMPT_STYLE` | 用途 |
|---|---|
| `auto`(預設) | 模型名稱含 `chandra` → 用 `chandra`,否則 `generic` |
| `chandra` | Chandra OCR 2 的**原生訓練提示**(英文)。用模型訓練時見過的提示,轉寫品質最好 |
| `generic` | 中文指示式提示。給 Qwen2.5-VL 等**通用** VLM 用 —— 它們沒見過 Chandra 的提示,但指令跟隨能力好,把規則講清楚反而更準 |

提示檔在 `app/prompts/`:`ocr_transcribe_en.md`(chandra)、
`ocr_transcribe_generic_zh.md`(generic)。`/api/v1/health` 的
`detail.promptStyle` 會顯示目前實際採用的風格。

---

## 3. 影像前處理

手機拍攝紀錄單最常見的三個辨識失敗原因,服務端會先處理(`app/preprocess.py`):

1. **EXIF 方向未套用** — 手機把照片存成橫向 + Orientation 標記。模型看到躺著的表單,
   辨識率會崩掉。這是「照片明明很清楚卻讀不出東西」的第一嫌疑。
2. **解析度過高** — 4000×3000 會被切成大量 image token,拖慢推論又稀釋注意力。
   長邊壓到 2000px 對手寫辨識最划算。
3. **對比不足** — 現場光線不均、鉛筆字淺,可開 `DMAT_PREPROCESS_ENHANCE=1`。

前端(`wwwroot/js/capture.js`)也做了對應處理:壓縮前以
`createImageBitmap(file, {imageOrientation:'from-image'})` 先套用方向。
**這步很關鍵** —— canvas 重新編碼後的 JPEG 不含 EXIF,若方向沒先套用,
躺著的畫面會被永久烙進像素,後端也救不回來。

---

## 4. REST API 介面(v1)

### 4.1 `POST /api/v1/ocr/analyze` — 影像辨識

multipart/form-data,欄位名 `file`(JPEG/PNG/HEIC 等 Pillow 可讀格式)。

```bash
curl -X POST --noproxy '*' http://localhost:8100/api/v1/ocr/analyze -F "file=@紀錄單.jpg"
```

回應(節錄):

```json
{
  "jobId": "e3f1…",
  "model": "datalab-to/chandra-ocr-2@http://localhost:8080(兩階段)",
  "isMock": false,
  "fields": {
    "triage":       { "value": "2",   "confidence": 0.90 },
    "patient_name": { "value": "陳○宏", "confidence": 0.88 },
    "trauma_superficial_injury": { "value": true, "confidence": 0.90 }
  },
  "warnings": [],
  "preprocess": { "originalSize": "3024x4032", "finalSize": "1500x2000", "exifTransposed": true },
  "stages": [
    { "stage": "ocr_transcribe", "elapsedMs": 41230, "chars": 3812 },
    { "stage": "structure_rules", "elapsedMs": 6, "extracted": 41 }
  ]
}
```

- 欄位鍵名與 `damt_db_fields.xlsx` 之 Field_Map.db_column 一致(頁 1 全欄位)。
- `value` 型別:文字欄=字串、數值欄=數字、勾選框=布林、空白=null。
- 信心門檻的判定在 **Web 應用端**(appsettings `Ocr` 區段),本服務只回報原始信心分數。
- **辨識失敗回 HTTP 502 + `{"error": "…"}`**,訊息會直接顯示在覆核畫面,
  不會靜默變成空白欄位。

兩階段模式的信心分數語意:代表「**擷取**的確定性」而非 OCR 字元正確率。
標籤命中且值格式合法 → 0.88;命中但格式可疑(如體溫 361)→ 0.62;找不到 → 0(必進覆核)。

### 4.2 `POST /api/v1/ocr/transcribe` — 只取 OCR 原始轉寫(診斷用)

當某欄位讀不到時,先看這裡就能分辨責任歸屬:

- 轉寫是**空的** → OCR 沒讀到(方向錯、影像太暗、mmproj 沒掛、模型未載入)
- 轉寫**有內容但欄位空** → 結構化規則沒對上,調整 `app/structurer.py` 的標籤字典

更方便的做法是用附的命令列工具:

```bash
cd src/ai-service
.venv/bin/python tools/try_image.py ../Dmat.Web/app_data/images/202607/<hash>.jpg
.venv/bin/python tools/try_image.py <照片> --raw     # 一併印出原始轉寫
```

### 4.3 `GET /api/v1/ocr/jobs/{jobId}` — 查詢辨識工作

回傳 `{"status": "completed", "result": {…}}` 或 `{"status": "failed", "error": "…"}`;
查無工作回 404。(目前為同步處理後留存紀錄;大量影像佇列化為後續擴充。)

### 4.4 `POST /api/v1/validate` — 資料合理性檢核

```bash
curl -X POST --noproxy '*' http://localhost:8100/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"fields": {"blood_pressure_systolic": 82, "triage": "3"}}'
```

回應:`{"warnings": ["SBP 82 低於 90,請確認休克風險", "生命徵象異常但檢傷分類為 3 非緊急,請確認分類"]}`

檢核規則:必填欄位缺漏(檢傷分類/性別/傷票編號)、生命徵象合理範圍
(體溫 30–45、脈搏 20–250、呼吸 4–60、收縮壓 40–300、舒張壓 20–200、血氧 50–100)、
臨床警示(SBP<90、SpO2<90%)、檢傷邏輯(生命徵象異常但分類為非緊急)。

### 4.5 `GET /api/v1/health` — 健康檢查

```json
{
  "status": "ok",
  "engineKey": "vision",
  "engine": "datalab-to/chandra-ocr-2@http://localhost:8080(兩階段)",
  "isMock": false,
  "engineReady": true,
  "detail": { "baseUrl": "http://localhost:8080", "twoStage": true },
  "preprocess": { "enabled": true, "maxEdge": 2000, "enhance": false },
  "queueLength": 0
}
```

- `isMock` 為 Web 端顯示警示橫幅的依據。
- `vision` 引擎會實際探測後端 `/v1/models`;`chandra_hf` 回報模型是否已載入完成
  (背景載入中時 `engineReady: false`,並附 `loadError`)。
- 引擎組態錯誤時回 **503** 並附原因,服務本身不會起不來。

---

## 5. 辨識品質調整

依「先確認 OCR 讀到了,再調結構化」的順序處理:

**第一階段(OCR 轉寫)**

- **提示詞**:`app/prompts/ocr_transcribe_en.md` 為 Chandra 的**原生訓練提示**,
  用模型訓練時見過的提示轉寫品質明顯較好。非必要不要改。
- **前處理**:先確認 `preprocess.finalSize` 是直立的。淺色手寫開 `DMAT_PREPROCESS_ENHANCE=1`。
- **輸出被截斷**:整頁表單轉寫可達數千字元,`DMAT_VISION_MAX_TOKENS` 不足會被切斷,
  後段欄位就全空。JSON 解析已能自動補上未閉合括號,但轉寫仍會缺內容。
- **量化版本**:精度不足時升級量化(Q4_K_M → Q6_K → Q8_0);Q2/Q3 系列精度明顯下降。

**第二階段(結構化)**

欄位規格集中在 **`app/field_spec.py`**,那是唯一事實來源:標籤同義詞、型別、
所屬區塊、允許值、數值範圍、格式樣式、長度上限都在那裡宣告。
勾選項目名稱在 `app/structurer.py` 的 `CHECKBOX_LABELS`。

若某欄位一直讀不到,把實際轉寫裡出現的印刷字加進該欄位的 `labels` 即可。

防止「欄位讀到別欄位資料」的四道機制:

1. **標籤完整性** — 命中的標籤若其實是更長標籤的一部分就不算數
   (`過敏` 命中在 `過敏史` 裡 → 略過)。
2. **儲存格 / 列邊界** — 值只能取自標籤所在的儲存格,或同列的下一格;
   **絕不跨列**。本格空白就是空白,不會去借下一列的值。
3. **候選評分** — 同一欄位的所有命中都列為候選,依「是否合規」「是否落在正確區塊」
   「是否混入別欄位標籤」評分後擇優,而不是取第一個命中就收工。
4. **嚴格驗證** — 依 `field_spec` 檢查型別/範圍/格式/長度,不合規者信心壓到 0.2,
   必定進入人工覆核。錯的資料比空白更危險。

**意識欄位(GCS)**支援三種填法,並自動正規化為統一格式:

| 表單上寫 | 系統顯示 | 說明 |
|---|---|---|
| `清` / `聲` / `痛` / `無` | 原樣 | AVPU |
| `15` | `15` | GCS 總分 |
| `15(E4V5M6)` | `15 (E4V5M6)` | 總分 + 分項,**兩者都保留** |
| `E3V4M5` | `12 (E3V4M5)` | 只有分項時自動補上總分 |

EVM 分項是臨床判讀依據 —— 同樣是 8 分,E1V1M6 與 E2V3M3 的處置方向不同,
只留總分等於把資訊丟了。因此意識欄標記 `keep_parens=True`,括號內容不會被
當成印刷註記剝掉(一般欄位的「(選填)」才要剝)。

同時利用 GCS 的性質做**免費的錯誤偵測**:總分必定等於 E+V+M,且 E≤4、V≤5、M≤6。
不符即代表其中一項被誤讀(手寫 4 與 9、1 與 7 容易混),信心壓到 0.2 送覆核 ——
值仍保留給覆核人員參考。

自由敘述欄位(`free_text=True`:現病史、過敏原、各類其他說明)刻意放寬:
病情描述本來就會出現「意識躁動」「右下肢開放性骨折」這種同時是別欄位標籤的字詞,
因此這類欄位只截在「標籤 + 冒號」樣式上,靠儲存格邊界與長度上限把關。

同名項目消歧靠 `SECTION_HINTS`(慢性病的「高血壓」vs 非創傷診斷的「高血壓」)。
勾選狀態採「**區段歸屬**」判斷:一個勾選框管到下一個勾選框或換行之前 ——
比用固定字元視窗前後找記號可靠,後者會把下一個項目的記號誤認成自己的。

改完務必跑測試:

```bash
python tests/test_structurer.py
python tests/test_no_cross_contamination.py    # 跨欄位污染回歸測試
```

**單階段模式(`DMAT_TWO_STAGE=0`)**

- 提示詞在 `app/prompts/page1_zh.md`。
- 輸出容錯:自動剝除 ```json 圍欄、修正全角引號/單引號/尾隨逗號、補齊未閉合括號、
  拆解 `{"fields": {...}}` 包裝、數值去單位(「36.5 度」→ 36.5)、
  勾選值正規化(是/有/✓/1 → true)、補齊缺漏欄位(信心 0 強制覆核)。

---

## 6. 測試

```bash
cd src/ai-service
for t in tests/test_*.py; do python "$t"; done

# 各檔用途
#   test_structurer.py                 結構化規則:HTML 轉寫 → 77 欄位
#   test_no_cross_contamination.py     欄位互相污染(標籤子字串、跨格、跨列、型別違規)
#   test_real_form_layout.py           以現場實際紀錄單版面為準的回歸測試
#   test_section_numbers_and_ticks.py  節次編號污染、勾選溢出降信心
#   test_pipeline.py                   REST + 前處理 + 錯誤處理
#   test_engine_switch.py              「模擬 → 真實」切換動作本身
```

三支測試都用**假的 OpenAI 相容端點**取代 vLLM,因此**不需要 GPU 或模型權重**即可執行。
涵蓋範圍:

- 請求格式(OpenAI 視覺 messages + base64 data URI)
- 兩階段流程與提示風格自動選擇
- EXIF 轉正與長邊縮放
- 引擎失敗時回傳可行動的錯誤訊息(而非靜默空白)
- 寫入 `.env` 後確實不再是 mock、且影像真的被送去推論

唯一無法在此驗證的是「**模型本身讀得多準**」—— 那需要真實權重與 GPU。
換句話說,除了模型辨識率之外,整條路都已被自動測試守住。

---

## 7. 疑難排解

| 症狀 | 處理 |
|---|---|
| **覆核畫面永遠是「陳○宏」** | 模擬引擎生效中。`health` 看 `isMock`;執行 `./scripts/setup-ocr.sh` 切換後,在覆核頁按「↻ 重新辨識」 |
| **重拍同一張照片還是舊結果** | SHA-256 去重會回傳既有紀錄。已修正為「前次辨識未成功時自動重跑」;要強制重跑請用「↻ 重新辨識」 |
| Web 端全部降級人工輸入 | 本服務未啟動或 8100 被占用;`curl --noproxy '*' http://localhost:8100/api/v1/health` |
| health 回 `engineReady: false` | `vision`:後端未啟動或端點設錯,檢查 `DMAT_VISION_BASE_URL`。`chandra_hf`:模型仍在載入,看 `detail.loadError` |
| 無法連線但端點明明有開 | 系統設了 `HTTP_PROXY`/`ALL_PROXY`。服務端已 `trust_env=False` 不走代理;用 curl 測試請加 `--noproxy '*'` |
| 辨識逾時 | 調高 `DMAT_VISION_TIMEOUT_S` 與 Web 端 `AiService:TimeoutSeconds`(已預設 300),或降低 `DMAT_PREPROCESS_MAX_EDGE` |
| 回傳欄位全空 | 用 `tools/try_image.py <照片> --raw` 看轉寫:空的→ mmproj 沒掛/影像方向錯;有內容→ 結構化字典沒對上 |
| 照片明明清楚卻讀不出來 | 檢查 `preprocess.finalSize` 是否為直立。`exifTransposed: false` 且寬>高 → 方向沒轉正 |
| **勾記號畫出格線,隔壁項目也被判成勾選** | 已由第三階段針對性複查處理(見 §2.1)。若仍不準:提高解析度 `DMAT_PREPROCESS_MAX_EDGE=2600`;拍攝時讓紀錄單填滿畫面、正對鏡頭、避免傾斜與反光 |
| **檢傷分類常常判錯** | 檢傷是單選,多格同時勾選時會自動觸發複查。仍不準表示影像上的勾記號本身難以辨識 —— 提高解析度或改善拍攝角度 |
| 欄位讀到節次編號(如姓名變成「陳柏厚 3.2」) | 已於 structurer 截斷;若出現新的版面,把該欄位的印刷字加進 `field_spec.py` 的 `labels` |
| 中文亂碼 | 確認以 UTF-8 讀取回應;服務端一律輸出 UTF-8 JSON |
