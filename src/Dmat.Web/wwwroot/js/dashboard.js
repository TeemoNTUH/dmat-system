// 儀表板即時更新:SignalR 推播 + 輪詢備援(架構書 4.2)
(function () {
    const POLL_MS = 10000;
    const connState = document.getElementById('connState');
    let signalrConnected = false;

    function setConn(ok) {
        signalrConnected = ok;
        connState.textContent = ok ? '即時連線' : '輪詢備援';
        connState.className = 'badge ' + (ok ? 'bg-success' : 'bg-warning text-dark');
    }

    function apply(s) {
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

        // --- 下方傷情態勢統計卡 ---
        set('statTotal', s.total);
        set('statRed', s.red);
        set('statYellow', s.yellow);
        set('statGreen', s.green);
        set('statBlack', s.black);
        set('statPalliative', s.palliative);
        set('statInCare', s.inCare);
        set('statAwaiting', s.awaitingEvacuation);
        set('statPending', s.pendingReview);

        // --- 上方戰情看板 ---
        // 伺服器端的計算屬性(blackOrPalliative、evacuation)在 JSON 中為 camelCase;
        // 舊版後端若尚未提供則就地補算,避免推播後畫面出現 undefined。
        const blackOrPalliative = s.blackOrPalliative ?? ((s.black || 0) + (s.palliative || 0));
        const evacuation = s.evacuation ?? ((s.awaitingEvacuation || 0) + (s.evacuating || 0));

        set('boardTotal', s.total);
        set('boardMale', s.male);
        set('boardFemale', s.female);
        set('boardOther', (s.otherGender || 0) + (s.unknownGender || 0));

        set('cntRed', s.red);
        set('cntYellow', s.yellow);
        set('cntGreen', s.green);
        set('cntBlack', blackOrPalliative);

        // 長條寬度 = 該類別人數 ÷ 總收治人數,四條相加為 100%,
        // 因此長度可直接讀成「佔全體傷患的比例」。
        // 演算法與 Razor 首次渲染一致(Views/Dashboard/Index.cshtml)。
        const denom = Math.max(1, s.total || 0);   // 尚無傷患時避免除以零
        // 長條只表達比例,實際人數由右側欄位顯示
        const bar = (id, n) => {
            const el = document.getElementById(id);
            if (el) el.style.width = ((n || 0) * 100 / denom) + '%';
        };
        bar('barRed', s.red);
        bar('barYellow', s.yellow);
        bar('barGreen', s.green);
        bar('barBlack', blackOrPalliative);

        set('boardInCare', s.inCare);
        set('boardEvac', evacuation);
        set('boardDeparted', s.departed);
        set('boardDeceased', s.deceased);

        // 直接災難相關比例:資料未接時後端回 null,顯示「—」而不是 0。
        // 0 會被讀成「統計後確實是零人」,那是假資訊。
        const dash = v => (v === null || v === undefined) ? '—' : v;
        set('boardDisasterDirect', dash(s.disasterDirect));
        set('boardDisasterIndirect', dash(s.disasterIndirect));
        set('boardDisasterUnrelated', dash(s.disasterUnrelated));
        const note = document.getElementById('boardDisasterNote');
        if (note) note.style.display = s.hasDisasterRelation ? 'none' : '';

        // 警示文字由後端依真實統計產生,前端只負責呈現(不重複判斷邏輯)
        if (Array.isArray(s.alerts)) set('boardAlerts', s.alerts.join(' | '));

        set('updatedAt', new Date().toLocaleTimeString('zh-TW', { hour12: false }));
    }

    async function poll() {
        if (signalrConnected) return; // SignalR 正常時不輪詢
        try {
            const resp = await fetch('/Dashboard/Summary');
            if (resp.ok) apply(await resp.json());
        } catch { /* 離線時靜默,恢復後自動更新 */ }
    }

    // 刪除傷患:不可逆,送出前要求明確確認。
    // 訊息刻意把「會連帶刪掉什麼」講清楚 —— 影像檔一併刪除是使用者最容易忽略的部分。
    document.querySelectorAll('form.js-delete-patient').forEach(form => {
        form.addEventListener('submit', e => {
            const tag = form.dataset.tag || '(無編號)';
            const name = form.dataset.name || '無名氏';
            const ok = confirm(
                `確定要刪除傷患「${tag} ${name}」嗎?\n\n` +
                '將永久刪除:\n' +
                '  ・傷患主檔與過去病史\n' +
                '  ・所有檢傷紀錄與初步診斷\n' +
                '  ・原始紀錄單影像(含磁碟上的照片檔)\n\n' +
                '此操作無法復原。'
            );
            if (!ok) e.preventDefault();
        });
    });

    const conn = new signalR.HubConnectionBuilder()
        .withUrl('/hubs/dashboard')
        .withAutomaticReconnect()
        .build();

    conn.on('summaryUpdated', s => {
        apply(s);
        // 傷患清單有異動時重新載入頁面下方「最近傷患」表(簡化作法)
        clearTimeout(window.__reloadTimer);
        window.__reloadTimer = setTimeout(() => location.reload(), 1500);
    });
    conn.onreconnecting(() => setConn(false));
    // 斷線重連成功後重新拉取完整統計快照(架構書 Q3)
    conn.onreconnected(() => { setConn(true); fetch('/Dashboard/Summary').then(r => r.json()).then(apply); });
    conn.start().then(() => setConn(true)).catch(() => setConn(false));

    setInterval(poll, POLL_MS);
})();
