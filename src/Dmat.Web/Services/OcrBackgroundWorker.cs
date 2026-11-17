using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

/// <summary>
/// 背景辨識服務:從 <see cref="OcrJobQueue"/> 取出影像辨識。
///
/// **同時處理張數由 <c>AiService:Concurrency</c> 決定(預設 1)。**
/// 早期假設「GB10 單卡同時只跑得動一張」,因此逐一處理;但實測轉寫階段是逐字輸出、
/// 受記憶體頻寬限制,GPU 算力多半閒置,而 vLLM 會把同時進來的請求合併批次處理,
/// 同時送 2~3 張通常每張只慢一些、整體每小時處理量明顯提升。
/// 實際上限依推論端記憶體與模型而定 —— 調高後請對照日誌「辨識耗時」確認單張沒有逼近
/// <c>AiService:TimeoutSeconds</c>。設為 1 即恢復逐一處理(覆核佇列順序與拍攝順序一致)。
/// 併發時完成順序可能與拍攝順序略有出入。
///
/// **同一張影像同一時間只會有一個工作者處理**(見 <see cref="OcrJobQueue.TryBeginProcessing"/>)。
///
/// **任何一張失敗都不能拖垮整個服務**:單張例外只記錄並繼續下一張。
/// 影像本身已存檔,失敗的那張會停在 ManualFallback,可在覆核頁按「↻ 重新辨識」重試。
/// </summary>
public class OcrBackgroundWorker(
    OcrJobQueue queue,
    IServiceScopeFactory scopeFactory,
    IConfiguration configuration,
    ILogger<OcrBackgroundWorker> logger) : BackgroundService
{
    /// <summary>防呆上限:設錯成很大的數字時,不至於一次把整個佇列都丟給推論伺服器。</summary>
    private const int MaxConcurrency = 8;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var concurrency = Math.Clamp(configuration.GetValue("AiService:Concurrency", 1), 1, MaxConcurrency);
        logger.LogInformation("背景辨識服務已啟動(同時處理 {Concurrency} 張)", concurrency);
        await RequeueUnfinishedAsync(stoppingToken);

        await Task.WhenAll(Enumerable.Range(1, concurrency)
            .Select(n => RunWorkerAsync(n, stoppingToken)));

        logger.LogInformation("背景辨識服務已停止");
    }

    /// <summary>單一工作者:不斷取出影像辨識,直到服務關閉。</summary>
    private async Task RunWorkerAsync(int workerNo, CancellationToken stoppingToken)
    {
        // 讓出執行緒,確保各工作者真的並行啟動,而不是第一個工作者在同步路徑上獨佔
        await Task.Yield();

        while (!stoppingToken.IsCancellationRequested)
        {
            Guid imageId;
            try
            {
                imageId = await queue.DequeueAsync(stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;   // 服務關閉
            }

            if (!queue.TryBeginProcessing(imageId))
            {
                logger.LogInformation(
                    "影像 {ImageId} 正由其他工作者辨識中,本次重新辨識要求將在其完成後自動排回佇列", imageId);
                continue;
            }

            try
            {
                // DbContext 是 Scoped,背景工作沒有請求範圍,必須自建一個
                using var scope = scopeFactory.CreateScope();
                var intake = scope.ServiceProvider.GetRequiredService<ImageIntakeService>();
                var result = await intake.ProcessAsync(imageId, stoppingToken);

                if (result.OcrSucceeded)
                    logger.LogInformation("背景辨識完成(工作者 {WorkerNo}):{ImageId}", workerNo, imageId);
                else
                    logger.LogWarning("背景辨識未成功(工作者 {WorkerNo}):{ImageId} — {Error}",
                        workerNo, imageId, result.OcrError);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                logger.LogInformation("服務關閉,影像 {ImageId} 的辨識中止(重啟後可用「重新辨識」重跑)", imageId);
                break;
            }
            catch (Exception ex)
            {
                // 單張失敗不得中斷佇列 —— 後面還有其他傷患的紀錄單在等
                logger.LogError(ex, "背景辨識發生未預期錯誤:{ImageId}", imageId);
            }
            finally
            {
                queue.EndProcessing(imageId);
            }
        }
    }

    /// <summary>
    /// 啟動時把「上次沒跑完」的影像重新排入佇列。
    ///
    /// 佇列本身在記憶體中,服務重啟就沒了。若不補這一步,程式中途重啟(或當機)
    /// 時仍停在 Queued/Recognizing 的影像會永遠卡住 —— 照片明明傳上來了卻不會被辨識,
    /// 而且沒有任何跡象。現場資料不能這樣默默消失。
    /// </summary>
    private async Task RequeueUnfinishedAsync(CancellationToken ct)
    {
        try
        {
            using var scope = scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<DmatDbContext>();

            var pending = await db.RecordImages
                .Where(i => i.Status == RecordImageStatus.Queued
                         || i.Status == RecordImageStatus.Recognizing)
                .OrderBy(i => i.UploadedAt)          // 依拍攝順序處理,與現場動線一致
                .Select(i => i.ImageId)
                .ToListAsync(ct);

            foreach (var id in pending) queue.Enqueue(id);

            if (pending.Count > 0)
                logger.LogInformation("已將 {Count} 張未完成辨識的影像重新排入佇列", pending.Count);
        }
        catch (Exception ex)
        {
            // 補排失敗不該讓服務起不來;那些影像仍可由覆核頁的「↻ 重新辨識」處理
            logger.LogError(ex, "重新排入未完成影像時發生錯誤");
        }
    }
}
