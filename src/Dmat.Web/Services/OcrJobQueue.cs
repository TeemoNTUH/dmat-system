using System.Threading.Channels;

namespace Dmat.Web.Services;

/// <summary>
/// 辨識工作佇列(架構書 4.1 步驟 3 之非同步化)。
///
/// **為什麼要有這一層**
///
/// 原本上傳端點會同步等待整個 OCR 跑完才回應。真實模型辨識一張紀錄單需 30~90 秒,
/// 加上針對性複查最多還有 4 輪推論 —— 一次上傳可能讓 HTTP 請求卡住好幾分鐘。
/// 手機端的離線佇列是逐張序列送出的,於是變成「拍完第二張要等第一張辨識完」,
/// 現場看起來就像當掉,重新整理頁面(等於中斷請求)反而才會繼續。
///
/// 現在上傳只做「存檔 + 入列」後立刻回應,辨識由背景服務接手。
/// 手機端因此能在數秒內把整批照片送完,離開現場也不影響後續辨識。
/// </summary>
public class OcrJobQueue
{
    // 無界佇列:現場單站的影像量有限,且寧可全部收下也不要拒收現場資料。
    // 背景服務逐一處理,不會因為佇列長就同時吃掉大量記憶體(佇列裡只有 Guid)。
    private readonly Channel<Guid> _channel = Channel.CreateUnbounded<Guid>(
        new UnboundedChannelOptions { SingleReader = true, SingleWriter = false });

    //: 已在佇列中等待的影像。**同一張影像不重複排隊。**
    //
    // 沒有這道去重,同一張照片會被辨識兩次以上。實際發生過的路徑:
    // 上傳請求慢 → 使用者以為當掉而重新整理 → 前端重送 → IntakeAsync 判定
    // 「這張已存在且尚未辨識成功」再排一次。兩次辨識各跑 30~90 秒搶同一張影像,
    // 白白佔用推論資源,還會互相覆寫結果。
    //
    // 只擋「還在排隊」的重複。已經被取出、正在辨識中的影像仍可再次排入 ——
    // 那代表使用者在看到結果後明確按了「重新辨識」,是新的意圖,不該吃掉。
    private readonly HashSet<Guid> _queued = [];
    private readonly object _gate = new();   // .NET 8:用 object,System.Threading.Lock 是 .NET 9 才有

    /// <summary>尚未開始處理的工作數(供狀態顯示)。</summary>
    public int Pending
    {
        get { lock (_gate) return _queued.Count; }
    }

    /// <summary>排入辨識佇列。已在佇列中則忽略,回傳 false。</summary>
    public bool Enqueue(Guid imageId)
    {
        lock (_gate)
        {
            if (!_queued.Add(imageId)) return false;
        }

        // UnboundedChannel 的 TryWrite 永遠成功;失敗只可能發生在 Complete() 之後
        if (_channel.Writer.TryWrite(imageId)) return true;

        lock (_gate) _queued.Remove(imageId);
        return false;
    }

    public async ValueTask<Guid> DequeueAsync(CancellationToken ct)
    {
        var id = await _channel.Reader.ReadAsync(ct);
        lock (_gate) _queued.Remove(id);
        return id;
    }
}
