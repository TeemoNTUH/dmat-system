"""DMAT AI 辨識服務(架構書 5.1/5.2):OCR + NLP 結構化 + 資料合理性檢核。

REST 介面(v1):
- POST /api/v1/ocr/analyze     上傳影像 → 欄位 JSON + 信心分數 + 警示
- POST /api/v1/ocr/transcribe  上傳影像 → 僅回傳 OCR 原始轉寫(診斷用)
- GET  /api/v1/ocr/jobs/{id}   查詢非同步工作
- POST /api/v1/validate        資料合理性檢核
- GET  /api/v1/health          健康檢查(引擎、模型載入狀態)

啟動:uvicorn app.main:app --host 0.0.0.0 --port 8100
"""
import logging
import uuid
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config
from .engines import EngineError, create_engine
from .preprocess import prepare_image
from .validators import validate_fields

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("dmat.ai")

app = FastAPI(title="DMAT AI 辨識服務", version="0.2.0")

try:
    engine = create_engine()
    _engine_init_error: str | None = None
except Exception as exc:  # noqa: BLE001 — 組態錯誤不應讓服務起不來,交由 /health 回報
    engine = None  # type: ignore[assignment]
    _engine_init_error = str(exc)
    logger.error("引擎初始化失敗:%s", exc)

if engine is not None and engine.is_mock:
    logger.warning(
        "⚠️ 目前使用模擬引擎(DMAT_ENGINE=%s):辨識結果為寫死的樣張假資料,與上傳影像無關。"
        "要進行真實辨識請設定 DMAT_ENGINE=vision 或 chandra_hf。",
        config.ENGINE,
    )

# 非同步工作紀錄(單機記憶體版;多工作站佇列為後續擴充)
_jobs: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 500


class ValidateRequest(BaseModel):
    fields: dict[str, Any]


def _require_engine():
    if engine is None:
        raise HTTPException(503, f"AI 引擎未就緒:{_engine_init_error}")
    return engine


async def _read_and_prepare(file: UploadFile):
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(400, "影像檔案為空")
    return prepare_image(image_bytes)



def describe_exception(exc: BaseException) -> str:
    """把例外轉成現場看得懂的一行說明。

    **不可只用 str(exc)。** 很多例外的訊息是空的 —— httpx.ConnectError()、
    RuntimeError() 這類不帶參數建構的例外,str() 就是空字串,
    格式化之後會變成「辨識發生未預期錯誤:」後面什麼都沒有。
    現場看到那一行完全不知道要查什麼,等於沒有錯誤訊息。

    因此訊息為空時改用型別名稱 —— 「ConnectError」至少指得出方向。
    """
    message = str(exc).strip()
    kind = type(exc).__name__
    detail = f"{kind}:{message}" if message else kind
    return f"辨識發生未預期錯誤({detail})"


@app.post("/api/v1/ocr/analyze")
async def analyze(file: UploadFile = File(...)):
    eng = _require_engine()
    prepared, content_type, pre_info = await _read_and_prepare(file)

    job_id = str(uuid.uuid4())
    try:
        output = await eng.analyze(prepared, content_type)
    except EngineError as exc:
        # 明確的引擎失敗:回 502 並附上人看得懂的原因,Web 端會顯示並降級為人工輸入
        logger.warning("辨識失敗(%s):%s", eng.name, exc)
        _remember(job_id, {"status": "failed", "error": str(exc), "engine": eng.name})
        return JSONResponse(
            status_code=502,
            content={"jobId": job_id, "model": eng.name, "error": str(exc), "preprocess": pre_info.to_dict()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("辨識發生未預期錯誤")
        _remember(job_id, {"status": "failed", "error": repr(exc), "engine": eng.name})
        return JSONResponse(
            status_code=500,
            content={"jobId": job_id, "model": eng.name, "error": describe_exception(exc)},
        )

    result: dict[str, Any] = {
        "jobId": job_id,
        "model": eng.name,
        "isMock": eng.is_mock,
        "fields": output.fields,
        "warnings": validate_fields(output.fields),
        "preprocess": pre_info.to_dict(),
        "stages": output.stages,
    }
    if eng.is_mock:
        result["warnings"] = [
            "⚠️ 目前為模擬引擎,以下欄位為樣張假資料,並非本張照片的辨識結果。",
            *result["warnings"],
        ]
    if config.RETURN_RAW:
        result["raw"] = output.raw

    _remember(job_id, {"status": "completed", "result": result})
    return result


@app.post("/api/v1/ocr/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """僅回傳 OCR 原始轉寫與前處理資訊,不做結構化。

    診斷用:當某欄位辨識不到時,先看這裡就能分辨是「OCR 沒讀到」還是「結構化沒對上」。
    """
    eng = _require_engine()
    prepared, content_type, pre_info = await _read_and_prepare(file)
    try:
        output = await eng.analyze(prepared, content_type)
    except EngineError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "model": eng.name,
        "isMock": eng.is_mock,
        "preprocess": pre_info.to_dict(),
        "stages": output.stages,
        "raw": output.raw,
    }


@app.get("/api/v1/ocr/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "查無此辨識工作")
    return job


@app.post("/api/v1/validate")
async def validate(req: ValidateRequest):
    return {"warnings": validate_fields(req.fields)}


@app.get("/api/v1/health")
async def health():
    if engine is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "engine": config.ENGINE, "error": _engine_init_error, "isMock": False},
        )

    described = await engine.describe()
    return {
        "status": "ok",
        "engineKey": config.ENGINE,
        "engine": engine.name,
        "isMock": engine.is_mock,
        "engineReady": described.get("ready", False),
        "detail": described,
        "preprocess": {
            "enabled": config.PREPROCESS_ENABLED,
            "maxEdge": config.PREPROCESS_MAX_EDGE,
            "enhance": config.PREPROCESS_ENHANCE,
        },
        "queueLength": 0,  # 同步處理版;佇列化後回報實際長度
    }


def _remember(job_id: str, payload: dict[str, Any]) -> None:
    if len(_jobs) >= _MAX_JOBS:
        _jobs.pop(next(iter(_jobs)))
    _jobs[job_id] = payload
