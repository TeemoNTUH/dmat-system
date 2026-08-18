"""AI 辨識服務組態(環境變數)。

推論引擎抽換不影響對 Web 應用之 REST 介面(架構書 5.4 註)。

可用引擎(DMAT_ENGINE):
- ``mock``       模擬引擎。**回傳寫死的台大樣張假資料,與上傳照片無關**,僅供介面開發/展示。
- ``vision``     通用 OpenAI 相容視覺端點(vLLM / SGLang / llama.cpp server / Ollama 皆可)。
- ``chandra``    ``vision`` 的別名,保留架構書 5.4 相同稱法。
- ``chandra_hf`` 本機 HuggingFace transformers 直接載入 Chandra OCR 2,不需另跑推論伺服器。

範例:

    # GB10 + vLLM(先跑 vllm serve datalab-to/chandra-ocr-2 --port 8080)
    DMAT_ENGINE=vision DMAT_VISION_BASE_URL=http://localhost:8080 \\
    DMAT_VISION_MODEL=datalab-to/chandra-ocr-2 uvicorn app.main:app --port 8100

    # GB10 本機推論,不另起伺服器(較慢但零額外服務)
    DMAT_ENGINE=chandra_hf uvicorn app.main:app --port 8100
"""
import os
from pathlib import Path


#: 引擎設定檔位置。預設 ai-service/.env(由 scripts/setup-ocr.sh 產生);
#: 以 DMAT_ENV_FILE 可指向集中管理的路徑(如 /etc/dmat/engine.env)。
ENV_FILE = os.getenv("DMAT_ENV_FILE") or str(Path(__file__).resolve().parent.parent / ".env")


def _load_env_file() -> None:
    """載入引擎設定檔(由 scripts/setup-ocr.sh 產生)。

    刻意不引入 python-dotenv:此檔格式極簡,少一個相依在離線現場部署更省事。
    已存在的環境變數優先,方便臨時以指令列覆寫單次設定
    (例如暫時切回 mock 做介面測試)。
    """
    env_path = Path(ENV_FILE)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


ENGINE = os.getenv("DMAT_ENGINE", "mock").strip().lower()

# ---- 通用 OpenAI 相容視覺端點 ----------------------------------------------
# llama.cpp:llama-server -m chandra-ocr-2-Q4_K_M.gguf --mmproj mmproj.gguf --port 8080
# vLLM(GB10):vllm serve datalab-to/chandra-ocr-2 --port 8080
# Ollama    :base url 填 http://localhost:11434(其 /v1 為 OpenAI 相容層)
VISION_BASE_URL = os.getenv(
    "DMAT_VISION_BASE_URL", os.getenv("DMAT_CHANDRA_BASE_URL", "http://localhost:8080")
).rstrip("/")
VISION_MODEL = os.getenv("DMAT_VISION_MODEL", os.getenv("DMAT_CHANDRA_MODEL", "datalab-to/chandra-ocr-2"))
VISION_API_KEY = os.getenv("DMAT_VISION_API_KEY", "")
VISION_TIMEOUT_S = float(os.getenv("DMAT_VISION_TIMEOUT_S", os.getenv("DMAT_CHANDRA_TIMEOUT_S", "300")))
VISION_MAX_TOKENS = int(os.getenv("DMAT_VISION_MAX_TOKENS", "8192"))
VISION_TEMPERATURE = float(os.getenv("DMAT_VISION_TEMPERATURE", "0.0"))

# 兩階段模式:先讓 OCR 模型輸出保留版面的 HTML,再把 HTML 轉成欄位。
# Chandra 這類 OCR 專用模型「照原樣轉寫」遠比「直接照自訂 schema 填 JSON」可靠,
# 因此預設開啟(對應架構書 5.1 的「OCR + NLP 結構化」兩段式設計)。
TWO_STAGE = _flag("DMAT_TWO_STAGE", True)

# 第一階段的轉寫提示風格:
# - ``chandra``:Chandra OCR 2 的原生訓練提示(英文)。用模型訓練時見過的提示,轉寫品質最好。
# - ``generic`` :中文指示式提示。給 Qwen2.5-VL 等**通用**視覺模型用 —— 它們沒見過
#                Chandra 的提示,但指令跟隨能力好,明確講清楚規則反而更準。
# 預設 auto:模型名稱含 chandra 就用 chandra 提示,否則用 generic。
PROMPT_STYLE = os.getenv("DMAT_PROMPT_STYLE", "auto").strip().lower()


def resolve_prompt_style(model_name: str) -> str:
    if PROMPT_STYLE in ("chandra", "generic"):
        return PROMPT_STYLE
    return "chandra" if "chandra" in model_name.lower() else "generic"


# 第三階段:針對性複查(app/verify.py)。
# 整頁轉寫時模型注意力被攤薄,勾選溢出、單選多勾、密集表格中的手寫編號容易出錯;
# 只問一個聚焦問題時判斷準確得多。代價是每次複查多一輪推論(數十秒),
# 因此只在偵測到不確定時觸發,並以 MAX_TASKS 設上限。
VERIFY_ENABLED = _flag("DMAT_VERIFY", True)
VERIFY_MAX_TASKS = int(os.getenv("DMAT_VERIFY_MAX_TASKS", "4"))

# ---- 本機 HuggingFace 推論(chandra_hf) -----------------------------------
HF_MODEL_ID = os.getenv("DMAT_HF_MODEL_ID", "datalab-to/chandra-ocr-2")
HF_DTYPE = os.getenv("DMAT_HF_DTYPE", "bfloat16")
HF_DEVICE_MAP = os.getenv("DMAT_HF_DEVICE_MAP", "auto")
HF_MAX_NEW_TOKENS = int(os.getenv("DMAT_HF_MAX_NEW_TOKENS", "8192"))

# ---- 影像前處理 -------------------------------------------------------------
PREPROCESS_ENABLED = _flag("DMAT_PREPROCESS", True)
PREPROCESS_MAX_EDGE = int(os.getenv("DMAT_PREPROCESS_MAX_EDGE", "2000"))
PREPROCESS_ENHANCE = _flag("DMAT_PREPROCESS_ENHANCE", False)
PREPROCESS_JPEG_QUALITY = int(os.getenv("DMAT_PREPROCESS_JPEG_QUALITY", "92"))

# ---- 除錯 -------------------------------------------------------------------
# 開啟後 /api/v1/ocr/analyze 會一併回傳模型原始輸出(raw),方便診斷
# 「為什麼某欄位辨識不到」。內含病患個資,正式環境請維持關閉。
RETURN_RAW = _flag("DMAT_RETURN_RAW", False)

MOCK_ENGINE_NAMES = ("mock", "demo", "sample")


def is_mock() -> bool:
    return ENGINE in MOCK_ENGINE_NAMES
