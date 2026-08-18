using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

/// <summary>
/// 背景辨識服務:從 <see cref="OcrJobQueue"/> 取出影像逐一辨識。
///
/// **逐一處理而非平行**:推論伺服器同時只跑得動一張紀錄單(GB10 單卡),
/// 平行送出只會讓每一張都變慢,還可能撞上記憶體上限。序列處理也讓
/// 覆核佇列的出現順序與拍攝順序一致,現場比較好對照。
///
/// **任何一張失敗都不能拖垮整個服務**:單張例外只記錄並繼續下一張。
/// 影像本身已存檔,失敗的那張會停在 ManualFallback,可在覆核頁按「↻ 重新辨識」重試。
/// </summary>
public class OcrBackgroundWorker(
    OcrJobQueue queue,
    IServiceScopeFactory scopeFactory,
    ILogger<OcrBackgroundWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation("背景辨識服務已啟動");
        await RequeueUnfinishedAsync(stoppingToken);

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

            try
            {
                // DbContext 是 Scoped,背景工作沒有請求範圍,必須自建一個
                using var scope = scopeFactory.CreateScope();
                var intake = scope.ServiceProvider.GetRequiredService<ImageIntakeService>();
                var result = await intake.ProcessAsync(imageId, stoppingToken);

                if (result.OcrSucceeded)
                    logger.LogInformation("背景辨識完成:{ImageId}", imageId);
                else
                    logger.LogWarning("背景辨識未成功:{ImageId} — {Error}", imageId, result.OcrError);
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
        }

        logger.LogInformation("背景辨識服務已停止");
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
