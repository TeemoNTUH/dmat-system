// 影像擷取與離線佇列(架構書 7.4.1):
// 拍攝影像先壓縮並寫入 IndexedDB 本地佇列,連上區網後自動逐張補傳。
// Android Chrome 支援 Background Sync;此處以「連線偵測 + 頁面開啟時重試」為主,涵蓋 iOS 備援。
(function () {
    const DB_NAME = 'dmat-capture';
    const STORE = 'uploadQueue';
    const MAX_DIM = 2200;      // 長邊上限,兼顧 OCR 品質與傳輸量
    const JPEG_QUALITY = 0.85;

    const fileInput = document.getElementById('fileInput');
    const btnCapture = document.getElementById('btnCapture');
    const queueList = document.getElementById('queueList');
    const resultList = document.getElementById('resultList');

    function openDb() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, 1);
            req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    async function enqueue(blob, name) {
        const db = await openDb();
        await new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, 'readwrite');
            tx.objectStore(STORE).add({ blob, name, addedAt: Date.now() });
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
        });
        await refreshQueueView();
    }

    async function allQueued() {
        const db = await openDb();
        return new Promise((resolve) => {
            const req = db.transaction(STORE).objectStore(STORE).getAll();
            req.onsuccess = () => resolve(req.result || []);
        });
    }

    async function remove(id) {
        const db = await openDb();
        await new Promise((resolve) => {
            const tx = db.transaction(STORE, 'readwrite');
            tx.objectStore(STORE).delete(id);
            tx.oncomplete = resolve;
        });
    }

    async function refreshQueueView() {
        const items = await allQueued();
        queueList.querySelectorAll('li[data-q]').forEach(li => li.remove());
        document.getElementById('queueEmpty').style.display = items.length ? 'none' : '';
        for (const it of items) {
            const li = document.createElement('li');
            li.className = 'list-group-item d-flex justify-content-between';
            li.dataset.q = it.id;
            li.innerHTML = `<span>📄 ${it.name}</span><span class="badge bg-secondary">待傳</span>`;
            queueList.appendChild(li);
        }
    }

    function addResult(text, ok, reviewUrl) {
        const li = document.createElement('li');
        li.className = 'list-group-item ' + (ok ? '' : 'list-group-item-warning');
        li.textContent = text;
        if (reviewUrl) {
            li.appendChild(document.createTextNode(' '));
            const a = document.createElement('a');
            a.href = reviewUrl;
            a.textContent = '前往覆核';
            a.className = 'small';
            li.appendChild(a);
        }
        resultList.prepend(li);
    }

    // 前端壓縮(架構書 4.1 步驟 1)
    //
    // ⚠ 方向問題:canvas 重新編碼後的 JPEG 不含 EXIF,所以「拍照時的旋轉資訊」
    // 必須在畫進 canvas 之前就套用,否則躺著的表單會被永久烙進像素,
    // 後端也救不回來(沒有 EXIF 可讀),辨識率會直接崩掉。
    // createImageBitmap(..., {imageOrientation:'from-image'}) 保證套用方向;
    // 不支援的瀏覽器退回 <img>(現代瀏覽器渲染 <img> 時亦會套用方向)。
    function drawToBlob(source, width, height) {
        const scale = Math.min(1, MAX_DIM / Math.max(width, height));
        const w = Math.round(width * scale);
        const h = Math.round(height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        canvas.getContext('2d').drawImage(source, 0, 0, w, h);
        return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
    }

    async function compress(file) {
        if (typeof createImageBitmap === 'function') {
            let bitmap;
            try {
                bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
            } catch (e) {
                bitmap = null; // 舊版瀏覽器不支援 options,退回 <img> 路徑
            }
            if (bitmap) {
                try {
                    return (await drawToBlob(bitmap, bitmap.width, bitmap.height)) || file;
                } finally {
                    if (bitmap.close) bitmap.close();
                }
            }
        }
        return new Promise((resolve) => {
            const img = new Image();
            const url = URL.createObjectURL(file);
            img.onload = async () => {
                const blob = await drawToBlob(img, img.naturalWidth, img.naturalHeight);
                URL.revokeObjectURL(url);
                resolve(blob || file);
            };
            img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
            img.src = url;
        });
    }

    // 上傳逾時。伺服器端只做「存檔 + 排入辨識佇列」後立刻回應,不再等 OCR,
    // 所以正常情況是數秒內完成;設 60 秒純粹是防止連線異常時整條佇列被一個請求卡死。
    const UPLOAD_TIMEOUT_MS = 60000;

    async function uploadOne(item) {
        const fd = new FormData();
        fd.append('file', item.blob, item.name);

        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), UPLOAD_TIMEOUT_MS);
        try {
            const resp = await fetch('/Capture/Upload', {
                method: 'POST', body: fd, signal: ctrl.signal
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        } finally {
            clearTimeout(timer);
        }
    }

    let flushing = false;
    async function flushQueue() {
        if (flushing || !navigator.onLine) return;
        flushing = true;
        try {
            // 送完一批後重新檢查佇列 —— 上傳期間新拍的照片會立刻接著送出。
            // 舊版只處理進入時的那份快照,期間拍的照片得等 15 秒輪詢才動,
            // 現場看起來就像「要重新整理才會繼續」。
            let items = await allQueued();
            while (items.length) {
                let aborted = false;
                for (const item of items) {
                    try {
                        const r = await uploadOne(item);
                        await remove(item.id);
                        // 辨識已改為背景處理,上傳成功只代表「伺服器收到並排入佇列」。
                        // 失敗原因仍要顯示出來,否則現場不知道為什麼沒動靜。
                        if (r.duplicate && r.ocrSucceeded) {
                            addResult(`${item.name}:影像重複(已併入既有紀錄)`, false, r.reviewUrl);
                        } else if (r.ocrError) {
                            addResult(`${item.name}:上傳成功,但辨識未啟動。${r.ocrError}`, false, r.reviewUrl);
                        } else {
                            addResult(`${item.name}:已上傳,辨識進行中`, true, r.reviewUrl);
                        }
                    } catch (e) {
                        console.warn('upload failed, will retry', e);
                        aborted = true;
                        break; // 斷線或伺服器異常:保留佇列,稍後重試
                    }
                    await refreshQueueView();   // 逐張更新,讓現場看得到進度
                }
                if (aborted) break;
                items = await allQueued();
            }
        } finally {
            flushing = false;
            await refreshQueueView();
        }
    }

    btnCapture.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
        for (const file of fileInput.files) {
            const blob = await compress(file);
            await enqueue(blob, file.name || ('capture-' + Date.now() + '.jpg'));
        }
        fileInput.value = '';
        flushQueue();
    });

    window.addEventListener('online', flushQueue);
    setInterval(flushQueue, 15000); // 補傳輪詢備援
    refreshQueueView().then(flushQueue);
})();
