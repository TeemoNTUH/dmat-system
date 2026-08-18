#!/usr/bin/env python3
"""對單張照片跑辨識並印出診斷資訊 —— 不必開瀏覽器就能查「為什麼讀不到」。

用法:
    cd src/ai-service
    .venv/bin/python tools/try_image.py ../Dmat.Web/app_data/images/202607/xxxx.jpg
    .venv/bin/python tools/try_image.py photo.jpg --raw       # 一併印出 OCR 原始轉寫
    .venv/bin/python tools/try_image.py photo.jpg --url http://192.168.0.10:8100

輸出的三段資訊各自對應不同的失敗原因:
- 引擎         :isMock=true → 看到的是樣張假資料,不是你的照片。
- 前處理       :finalSize 若仍是躺著的(寬>高),多半是方向沒轉正。
- 原始轉寫(--raw):若這段是空的或亂碼 → OCR 沒讀到,問題在影像品質或模型;
                    若這段讀得出來但欄位是空的 → 問題在結構化規則(app/structurer.py)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("請先安裝相依:pip install -r requirements.txt")


def main() -> int:
    ap = argparse.ArgumentParser(description="DMAT OCR 單張診斷工具")
    ap.add_argument("image", type=Path, help="影像檔路徑")
    ap.add_argument("--url", default="http://127.0.0.1:8100", help="AI 服務位址")
    ap.add_argument("--raw", action="store_true", help="一併取得 OCR 原始轉寫")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    if not args.image.is_file():
        return _fail(f"找不到影像:{args.image}")

    base = args.url.rstrip("/")
    # trust_env=False:本機端點不可走系統代理設定
    client = httpx.Client(timeout=args.timeout, trust_env=False)

    # 1) 引擎狀態
    try:
        health = client.get(f"{base}/api/v1/health").json()
    except httpx.HTTPError as exc:
        return _fail(f"無法連線至 AI 服務 {base}:{exc}\n請先啟動:python -m uvicorn app.main:app --port 8100")

    print("=" * 68)
    print(f"引擎      : {health.get('engine')}  (key={health.get('engineKey')})")
    print(f"就緒      : {health.get('engineReady')}")
    print(f"前處理    : {health.get('preprocess')}")
    if health.get("isMock"):
        print("\n⚠ 目前是模擬引擎 —— 以下欄位是寫死的樣張假資料,與這張照片無關。")
        print("  請執行 ../../scripts/setup-ocr.sh 切換為真實引擎後重跑。")
    print("=" * 68)

    endpoint = "transcribe" if args.raw else "analyze"
    files = {"file": (args.image.name, args.image.read_bytes(), "image/jpeg")}
    resp = client.post(f"{base}/api/v1/ocr/{endpoint}", files=files)

    if resp.status_code >= 400:
        body = _json_or_text(resp)
        print(f"\n✗ 辨識失敗(HTTP {resp.status_code})")
        print(f"  原因:{body.get('error') or body.get('detail') or resp.text[:400]}")
        return 1

    data = resp.json()
    print(f"\n前處理    : {json.dumps(data.get('preprocess', {}), ensure_ascii=False)}")
    for stage in data.get("stages", []):
        print(f"階段      : {json.dumps(stage, ensure_ascii=False)[:300]}")

    if args.raw:
        for name, text in (data.get("raw") or {}).items():
            print(f"\n--- OCR 原始輸出({name},共 {len(text)} 字元)---")
            print(text[:4000])
            if len(text) > 4000:
                print(f"…(其餘 {len(text) - 4000} 字元省略)")
        return 0

    fields = data.get("fields", {})
    filled = {k: v for k, v in fields.items() if v.get("value") not in (None, "", False)}
    print(f"\n辨識到 {len(filled)} / {len(fields)} 欄:")
    for key, val in filled.items():
        print(f"  {key:42s} = {val['value']!r:24s} conf={val['confidence']}")

    missing_required = [
        k for k in ("triage", "gender", "patient_tag_id") if fields.get(k, {}).get("value") in (None, "")
    ]
    if missing_required:
        print(f"\n⚠ 必填欄位仍缺漏:{', '.join(missing_required)}")
    for w in data.get("warnings", []):
        print(f"⚠ {w}")

    if not filled:
        print("\n沒有任何欄位被辨識出來。請加上 --raw 再跑一次:")
        print("  轉寫是空的  → OCR 讀不到(影像太暗/方向錯/模型未載入視覺層)")
        print("  轉寫有內容  → 結構化規則沒對上,請調整 app/structurer.py 的標籤字典")
    return 0


def _json_or_text(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
