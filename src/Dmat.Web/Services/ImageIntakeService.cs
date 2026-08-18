using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services.Ocr;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

public record IntakeResult(RecordImage Image, bool IsDuplicate, bool OcrSucceeded, string? OcrError = null);

/// <summary>
/// 影像擷取模組(架構書 4.1):存檔、SHA-256 去重、建立 RecordImage、呼叫 AI 辨識。
/// </summary>
public class ImageIntakeService(
    DmatDbContext db,
    OcrClient ocrClient,
    AuditService audit,
    OcrJobQueue jobQueue,
    IConfiguration config,
    IWebHostEnvironment env,
    ILogger<ImageIntakeService> logger)
{
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    public async Task<IntakeResult> IntakeAsync(IFormFile file, Guid? userId, CancellationToken ct = default)
    {
        // 1. 讀入並計算 SHA-256(完整性 + 多路徑交付去重,架構書 7.4.2/8.3)
        await using var ms = new MemoryStream();
        await file.CopyToAsync(ms, ct);
        var bytes = ms.ToArray();
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

        var existing = await db.RecordImages.Include(i => i.OcrResult)
            .FirstOrDefaultAsync(i => i.FileHash == hash, ct);
        if (existing is not null)
        {
            // 同一張影像已入庫。若前次辨識尚未成功(AI 服務當時未啟動、或引擎剛換成真實引擎),
            // 重新排入辨識佇列 — 否則使用者會卡在「重拍同一張也永遠拿到舊結果」的死結。
            if (NeedsAnalysis(existing))
            {
                existing.Status = RecordImageStatus.Queued;
                await db.SaveChangesAsync(ct);
                jobQueue.Enqueue(existing.ImageId);
                return new IntakeResult(existing, IsDuplicate: true, OcrSucceeded: false, OcrError: null);
            }
            return new IntakeResult(existing, IsDuplicate: true, OcrSucceeded: true);
        }

        // 2. 存入檔案儲存區
        var root = config["ImageStorage:Root"] ?? "./data/images";
        var dir = Path.Combine(env.ContentRootPath, root, DateTime.UtcNow.ToString("yyyyMM"));
        Directory.CreateDirectory(dir);
        var ext = Path.GetExtension(file.FileName) is { Length: > 0 } e ? e.ToLowerInvariant() : ".jpg";
        var filePath = Path.Combine(dir, hash + ext);
        await File.WriteAllBytesAsync(filePath, bytes, ct);

        var image = new RecordImage
        {
            // 一律以斜線儲存,避免資料庫跨平台搬移後路徑失效(見 RecordImagePath)
            FilePath = RecordImagePath.ToStorage(Path.GetRelativePath(env.ContentRootPath, filePath)),
            FileHash = hash,
            UploadedById = userId,
            Status = RecordImageStatus.Queued,
        };
        db.RecordImages.Add(image);
        audit.Log("ImageUpload", nameof(RecordImage), image.ImageId.ToString(), $"hash={hash[..12]}…");
        await db.SaveChangesAsync(ct);

        // 3. 排入背景辨識佇列後立刻回應。
        //    **不在此同步等待 OCR** —— 一張紀錄單的推論要數十秒到數分鐘,
        //    同步等待會讓手機端的上傳佇列整個卡住(見 OcrJobQueue 的說明)。
        jobQueue.Enqueue(image.ImageId);
        logger.LogInformation("影像 {ImageId} 已入庫並排入辨識佇列(佇列長度 {Pending})",
            image.ImageId, jobQueue.Pending);

        return new IntakeResult(image, false, OcrSucceeded: false, OcrError: null);
    }

    /// <summary>
    /// 背景服務呼叫:對已入庫的影像執行辨識。
    /// 與 <see cref="ReanalyzeAsync"/> 的差別只在於不擋「已覆核」—— 佇列裡不會有那種影像。
    /// </summary>
    public async Task<IntakeResult> ProcessAsync(Guid imageId, CancellationToken ct = default)
    {
        var image = await db.RecordImages.Include(i => i.OcrResult)
            .FirstOrDefaultAsync(i => i.ImageId == imageId, ct);
        if (image is null)
            return new IntakeResult(new RecordImage { ImageId = imageId }, false, false, "影像已不存在(可能已被刪除)");

        // 排隊期間可能已被覆核或刪除,避免覆蓋掉人工確認過的結果
        if (image.Status == RecordImageStatus.Committed)
            return new IntakeResult(image, false, false, "影像已完成覆核,略過背景辨識");

        var path = RecordImagePath.Resolve(env, image.FilePath);
        if (!File.Exists(path))
            return new IntakeResult(image, false, false, $"影像檔案不存在:{image.FilePath}");

        var bytes = await File.ReadAllBytesAsync(path, ct);
        var attempt = await RunAnalysisAsync(image, bytes, Path.GetFileName(path), ct);
        return new IntakeResult(image, false, attempt.Succeeded, attempt.Error);
    }

    /// <summary>
    /// 對已入庫的影像重新執行辨識(覆核介面「重新辨識」)。
    /// 換了推論引擎、調整了信心門檻、或 AI 服務先前沒開時,不必重新拍照即可重跑。
    /// </summary>
    public async Task<IntakeResult> ReanalyzeAsync(Guid imageId, CancellationToken ct = default)
    {
        var image = await db.RecordImages.Include(i => i.OcrResult)
            .FirstOrDefaultAsync(i => i.ImageId == imageId, ct)
            ?? throw new InvalidOperationException($"查無影像 {imageId}");

        if (image.Status == RecordImageStatus.Committed)
            return new IntakeResult(image, false, false, "此影像已完成覆核並寫入傷患主檔,不再重新辨識。");

        if (!RecordImagePath.Exists(env, image.FilePath))
            return new IntakeResult(image, false, false, $"影像檔案不存在:{image.FilePath}");

        audit.Log("ImageReanalyze", nameof(RecordImage), image.ImageId.ToString(),
            $"previousModel={image.OcrResult?.ModelName ?? "(無)"}");

        // 與上傳走同一條佇列:一次辨識含針對性複查可達數分鐘,
        // 同步等待會讓瀏覽器空轉、甚至超過 HTTP 逾時而顯示成失敗。
        image.Status = RecordImageStatus.Queued;
        await db.SaveChangesAsync(ct);
        jobQueue.Enqueue(image.ImageId);

        return new IntakeResult(image, false, OcrSucceeded: false, OcrError: null);
    }

    /// <summary>尚未有可用辨識結果(未辨識、降級、或前次為失敗紀錄)。</summary>
    private static bool NeedsAnalysis(RecordImage image) =>
        image.Status is RecordImageStatus.Queued or RecordImageStatus.Recognizing or RecordImageStatus.ManualFallback
        || image.OcrResult is null;

    /// <summary>執行辨識並寫入(或覆寫)OcrResult,同步更新影像狀態。</summary>
    private async Task<OcrAttempt> RunAnalysisAsync(
        RecordImage image, byte[] bytes, string fileName, CancellationToken ct)
    {
        image.Status = RecordImageStatus.Recognizing;
        // 這裡同樣可能撞上「影像剛被刪掉」——雖然視窗只有幾毫秒,
        // 但若不處理,日誌會把它記成「未預期錯誤」,誤導後續追查。
        if (!await TrySaveAnalysisAsync(image.ImageId, ct))
            return OcrAttempt.Fail("影像在辨識開始前已被刪除。");

        using var stream = new MemoryStream(bytes, writable: false);
        var attempt = await ocrClient.AnalyzeAsync(stream, fileName, ct);

        // 覆核尚未完成前可重複辨識,舊結果直接覆寫(已覆核者由 ReanalyzeAsync 擋掉)。
        //
        // **必須重新查資料庫,不可只看 image.OcrResult。** 兩個理由:
        //
        // 1. OcrResult 是導覽屬性,只有呼叫端做了 .Include(i => i.OcrResult) 才會被填。
        //    漏掉 Include 的話,明明已有結果的影像會被判成「新的」而 INSERT 第二筆,
        //    撞上 OcrResults.ImageId 的唯一鍵。
        // 2. 更關鍵:上面那行 AnalyzeAsync 會跑 30~90 秒。這段期間同一張影像
        //    可能已被另一次辨識寫入結果(現場重複觸發、或使用者中斷後重試),
        //    而 image.OcrResult 是那之前的舊快照。
        //    日誌中 25 次「UNIQUE constraint failed: OcrResults.ImageId」都是這樣來的 ——
        //    上傳請求跑了 116 秒,使用者以為當掉而重新整理,於是同一張跑了兩次。
        var slot = await db.OcrResults.FirstOrDefaultAsync(r => r.ImageId == image.ImageId, ct);
        var isNew = slot is null;
        slot ??= new OcrResult { ImageId = image.ImageId };
        // 同步導覽屬性:呼叫端(如覆核頁訊息)會直接讀 image.OcrResult.ModelName
        image.OcrResult = slot;

        if (!attempt.Succeeded)
        {
            // 降級為人工輸入(架構書 5.3)。仍寫一筆結果紀錄,把失敗原因帶到覆核畫面 —
            // 否則現場只看到一片空白欄位,無法判斷是 AI 沒開還是模型讀不出來。
            var diagnostic = new OcrAnalyzeResult
            {
                Model = "(辨識失敗)",
                Warnings = [$"AI 辨識未成功,已切換為人工輸入模式。原因:{attempt.Error}"],
            };
            slot.ResultJson = JsonSerializer.Serialize(diagnostic, JsonOpts);
            slot.ModelName = "(辨識失敗)";
            slot.ReviewStatus = ReviewStatus.Pending;
            if (isNew) db.OcrResults.Add(slot);
            image.Status = RecordImageStatus.ManualFallback;
            if (!await TrySaveAnalysisAsync(image.ImageId, ct))
                return OcrAttempt.Fail("影像在辨識期間已被刪除,結果未寫入。");
            logger.LogWarning("影像 {ImageId} 辨識失敗:{Error}", image.ImageId, attempt.Error);
            return attempt;
        }

        var result = attempt.Result!;
        ApplyConfidenceThresholds(result);
        slot.ResultJson = JsonSerializer.Serialize(result, JsonOpts);
        slot.ModelName = Truncate(result.Model, 100);
        slot.ReviewStatus = ReviewStatus.Pending;
        slot.ReviewedJson = null;
        slot.ReviewedById = null;
        slot.ReviewedAt = null;
        if (isNew) db.OcrResults.Add(slot);

        image.Status = RecordImageStatus.PendingReview;
        if (!await TrySaveAnalysisAsync(image.ImageId, ct))
            return OcrAttempt.Fail("影像在辨識期間已被刪除,結果未寫入。");

        logger.LogInformation("影像 {ImageId} 辨識完成(模型 {Model},mock={IsMock}),進入覆核佇列",
            image.ImageId, result.Model, result.IsMock);
        return attempt;
    }

    /// <summary>
    /// 寫入辨識結果。影像在辨識期間被刪除時回傳 false,不拋例外。
    ///
    /// 一次辨識要 30~90 秒,這段期間站長完全可能從覆核佇列把這張影像刪掉
    /// (拍糊了、重複了)。刪除是使用者明確的意思,辨識結果本來就不該再寫回去 ——
    /// 硬寫會讓 EF 丟出 DbUpdateConcurrencyException(預期影響 1 列、實際 0 列),
    /// 在日誌裡看起來像系統故障,實際上只是「東西被刪了」這件再正常不過的事。
    /// </summary>
    private async Task<bool> TrySaveAnalysisAsync(Guid imageId, CancellationToken ct)
    {
        try
        {
            await db.SaveChangesAsync(ct);
            return true;
        }
        catch (DbUpdateConcurrencyException)
        {
            logger.LogInformation("影像 {ImageId} 在辨識期間已被刪除,略過結果寫入", imageId);
            db.ChangeTracker.Clear();   // 這個 DbContext 的追蹤狀態已不可信,清掉避免污染後續操作
            return false;
        }
    }

    /// <summary>低於門檻之欄位標示 needReview(門檻可依欄位個別設定,appsettings Ocr 區段)</summary>
    private void ApplyConfidenceThresholds(OcrAnalyzeResult result)
    {
        var defaultThreshold = config.GetValue("Ocr:DefaultConfidenceThreshold", 0.85);
        // appsettings 的數值一律為 invariant 格式,不可受請求文化影響
        var overrides = config.GetSection("Ocr:FieldThresholds").GetChildren()
            .ToDictionary(
                c => c.Key,
                c => double.TryParse(c.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
                    ? v
                    : defaultThreshold);

        foreach (var (key, field) in result.Fields)
        {
            var threshold = overrides.GetValueOrDefault(key, defaultThreshold);
            if (field.Confidence < threshold)
                field.NeedReview = true;
        }
    }

    /// <summary>OcrResult.ModelName 上限 100 字元(見 Imaging.cs);真實引擎名稱含端點會超長。</summary>
    private static string Truncate(string value, int max) =>
        value.Length <= max ? value : value[..max];
}
