using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

/// <summary>傷患刪除結果摘要,供稽核紀錄與畫面訊息使用。</summary>
public record PatientDeletionResult(
    string TagNo,
    string? Name,
    int TriageRecords,
    int Diagnoses,
    int Images,
    int ImageFilesDeleted,
    int ImageFilesMissing)
{
    public string Describe() =>
        $"檢傷紀錄 {TriageRecords} 筆、診斷 {Diagnoses} 筆、影像 {Images} 張" +
        (ImageFilesMissing > 0 ? $"(實體檔案刪除 {ImageFilesDeleted}、找不到 {ImageFilesMissing})" : "");
}

/// <summary>單張影像刪除結果。<c>Refused</c> 有值代表被安全規則擋下,未執行刪除。</summary>
public record ImageDeletionResult(string HashPrefix, bool FileDeleted, string? Refused = null)
{
    public bool Succeeded => Refused is null;
}

/// <summary>
/// 資料刪除(演練資料清理用):傷患整筆,以及覆核佇列中的單張影像。
///
/// **設計取捨**
///
/// 這是本系統唯二的破壞性操作,因此:
/// - 刪除行為一律寫入 AuditLog。AuditLog 僅增查、不可刪改(架構書 8.4),
///   因此「誰在何時刪了什麼」的軌跡會留存下來 —— 資料可以刪,刪除這件事不能被抹掉。
/// - 採實體刪除而非軟刪除:現場需求是清掉演練資料並釋出影像空間,
///   且 RecordImage.FileHash 有唯一索引,不實際刪除的話同一張照片無法重新上傳測試。
///   正式導入若需保留「已刪除」狀態以供追溯,應改為軟刪除並調整去重邏輯。
///
/// **刪除順序**
///
/// DbContext 未設定串聯刪除,且 RecordImage.PatientId 可為空(預設 ClientSetNull),
/// 直接刪 Patient 會失敗或留下孤兒列。因此由葉節點往回刪:
/// OcrResult → RecordImage(含磁碟檔案)→ DiagnosisRecord → TriageRecord → PastHistory → Patient
/// </summary>
public class PatientDeletionService(
    DmatDbContext db,
    AuditService audit,
    IWebHostEnvironment env,
    ILogger<PatientDeletionService> logger)
{
    // -----------------------------------------------------------------------
    // 傷患整筆刪除
    // -----------------------------------------------------------------------
    public async Task<PatientDeletionResult?> DeleteAsync(Guid patientId, CancellationToken ct = default)
    {
        var patient = await db.Patients
            .Include(p => p.TriageRecords)
            .Include(p => p.Diagnoses)
            .Include(p => p.PastHistory)
            .Include(p => p.Images).ThenInclude(i => i.OcrResult)
            .FirstOrDefaultAsync(p => p.PatientId == patientId, ct);
        if (patient is null) return null;

        var images = patient.Images.ToList();
        var result = new PatientDeletionResult(
            TagNo: patient.TagNo ?? "(無編號)",
            Name: patient.Name,
            TriageRecords: patient.TriageRecords.Count,
            Diagnoses: patient.Diagnoses.Count,
            Images: images.Count,
            ImageFilesDeleted: 0,
            ImageFilesMissing: 0);

        // 1. 影像的辨識結果
        foreach (var image in images)
        {
            if (image.OcrResult is not null) db.OcrResults.Remove(image.OcrResult);
        }

        // 2. 影像資料列(實體檔案在資料庫異動成功後才刪,見步驟 6)
        db.RecordImages.RemoveRange(images);

        // 3~5. 診斷、檢傷紀錄、過去病史
        db.DiagnosisRecords.RemoveRange(patient.Diagnoses);
        db.TriageRecords.RemoveRange(patient.TriageRecords);
        if (patient.PastHistory is not null) db.PastHistories.Remove(patient.PastHistory);

        RemovePendingSyncLogs(patientId, await LoadSyncLogsAsync(patientId, ct));

        // 6. 傷患主檔
        db.Patients.Remove(patient);

        audit.Log("PatientDelete", nameof(Patient), patientId.ToString(),
            $"tagNo={result.TagNo} name={patient.Name ?? "(無名氏)"} {result.Describe()}");

        await db.SaveChangesAsync(ct);

        var (deleted, missing) = DeleteFiles(images);
        logger.LogInformation("已刪除傷患 {TagNo}({PatientId}):{Detail}",
            result.TagNo, patientId, result.Describe());

        return result with { ImageFilesDeleted = deleted, ImageFilesMissing = missing };
    }

    // -----------------------------------------------------------------------
    // 覆核佇列:單張影像刪除
    // -----------------------------------------------------------------------
    /// <summary>
    /// 刪除一張尚未覆核的紀錄單影像(含辨識結果與磁碟檔案)。
    ///
    /// **安全規則:已覆核的影像不得由此刪除。**
    /// 一旦覆核完成,該影像就是某位傷患病歷的原始憑證(架構書 8.4 責任追溯),
    /// 從佇列端單獨刪掉會讓傷患資料失去出處、卻沒有任何跡象。
    /// 要移除那種影像,只能連同傷患整筆刪除 —— 那條路徑限系統管理者且會完整記錄。
    /// </summary>
    public async Task<ImageDeletionResult?> DeleteImageAsync(Guid imageId, CancellationToken ct = default)
    {
        var image = await db.RecordImages
            .Include(i => i.OcrResult)
            .FirstOrDefaultAsync(i => i.ImageId == imageId, ct);
        if (image is null) return null;

        var hashPrefix = image.FileHash.Length >= 8 ? image.FileHash[..8] : image.FileHash;

        if (image.Status == RecordImageStatus.Committed || image.PatientId is not null)
        {
            logger.LogWarning("拒絕刪除已覆核影像 {ImageId}(已綁定傷患 {PatientId})", imageId, image.PatientId);
            return new ImageDeletionResult(hashPrefix, false,
                "此影像已完成覆核並成為傷患病歷的原始憑證,不能單獨刪除。" +
                "若確定要移除,請從儀表板刪除整位傷患。");
        }

        if (image.OcrResult is not null) db.OcrResults.Remove(image.OcrResult);
        db.RecordImages.Remove(image);

        audit.Log("ImageDelete", nameof(RecordImage), imageId.ToString(),
            $"hash={hashPrefix}… status={image.Status} uploadedAt={image.UploadedAt:o}");

        await db.SaveChangesAsync(ct);

        var (deleted, _) = DeleteFiles([image]);
        logger.LogInformation("已刪除待覆核影像 {ImageId}(hash={Hash}…)", imageId, hashPrefix);
        return new ImageDeletionResult(hashPrefix, deleted > 0);
    }

    // -----------------------------------------------------------------------
    private Task<List<SyncLog>> LoadSyncLogsAsync(Guid patientId, CancellationToken ct)
    {
        // 大小寫注意:SyncLog.RecordId 是用 Guid.ToString() 寫入的(小寫),
        // 而 EF Core 在 SQLite 是以大寫字串保存 Guid 主鍵。兩者字面不同,
        // 直接比對會因為 SQLite 字串比較區分大小寫而永遠不match。
        // 故一律轉小寫比對(EF 會翻成 SQL lower(),SQLite/SqlServer 皆適用)。
        var idText = patientId.ToString().ToLowerInvariant();
        return db.SyncLogs
            .Where(s => s.TableName == nameof(Patient) && s.RecordId.ToLower() == idText)
            .ToListAsync(ct);
    }

    /// <summary>
    /// 移除待同步紀錄:此傷患已不存在,留著會讓同步服務嘗試上傳不存在的資料。
    ///
    /// 【預留】SyncLog 目前沒有「操作類型」欄位,無法表達「這筆是刪除」。
    /// 架構書 7.6 實作中央同步時需補上操作類型,否則中央端會保留一筆本地已刪除的傷患。
    /// </summary>
    private void RemovePendingSyncLogs(Guid patientId, List<SyncLog> logs) => db.SyncLogs.RemoveRange(logs);

    /// <summary>
    /// 刪除磁碟上的影像檔。**務必在資料庫異動成功之後才呼叫。**
    ///
    /// 順序刻意如此:檔案刪不掉還能重來(只是留下孤兒檔),
    /// 但若先刪檔案卻在存檔時失敗,就會變成「資料還在、影像不見了」—— 那是無法復原的。
    /// </summary>
    private (int Deleted, int Missing) DeleteFiles(IReadOnlyCollection<RecordImage> images)
    {
        var deleted = 0;
        var missing = 0;
        foreach (var image in images)
        {
            var path = RecordImagePath.Resolve(env, image.FilePath);
            try
            {
                if (File.Exists(path)) { File.Delete(path); deleted++; }
                else missing++;
            }
            catch (Exception ex)
            {
                missing++;
                logger.LogWarning(ex, "刪除影像檔案失敗:{Path}", path);
            }
        }
        return (deleted, missing);
    }
}
