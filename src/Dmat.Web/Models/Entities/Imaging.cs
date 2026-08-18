using System.ComponentModel.DataAnnotations;

namespace Dmat.Web.Models.Entities;

public enum RecordImageStatus : byte
{
    /// <summary>已上傳,等待 AI 辨識</summary>
    Queued = 0,
    /// <summary>辨識中</summary>
    Recognizing = 1,
    /// <summary>辨識完成,待人工覆核</summary>
    PendingReview = 2,
    /// <summary>覆核完成,已寫入傷患主檔</summary>
    Committed = 3,
    /// <summary>AI 服務失效,降級為人工輸入(架構書 5.3)</summary>
    ManualFallback = 4,
}

/// <summary>紀錄單影像(架構書 6.2.3)。SHA-256 雜湊確保完整性並供多路徑交付去重。</summary>
public class RecordImage
{
    public Guid ImageId { get; set; } = Guid.NewGuid();

    /// <summary>辨識或覆核後綁定傷患(上傳當下可空)</summary>
    public Guid? PatientId { get; set; }
    public Patient? Patient { get; set; }

    [MaxLength(260)]
    public string FilePath { get; set; } = "";

    /// <summary>SHA-256(hex, 64 字元)</summary>
    [MaxLength(64)]
    public string FileHash { get; set; } = "";

    /// <summary>多頁表冊之頁碼(本切片僅處理頁 1)</summary>
    public byte PageNo { get; set; } = 1;

    public RecordImageStatus Status { get; set; } = RecordImageStatus.Queued;

    public DateTime UploadedAt { get; set; } = DateTime.UtcNow;
    public Guid? UploadedById { get; set; }

    public OcrResult? OcrResult { get; set; }
}

public enum ReviewStatus : byte { Pending = 0, Confirmed = 1, Corrected = 2 }

/// <summary>AI 辨識結果(架構書 6.2.3)。原始結果與人工修正差異完整保留,供品質分析與責任追溯。</summary>
public class OcrResult
{
    public Guid OcrResultId { get; set; } = Guid.NewGuid();

    public Guid ImageId { get; set; }
    public RecordImage? Image { get; set; }

    /// <summary>AI 服務回傳之結構化 JSON(含各欄位信心分數)</summary>
    public string ResultJson { get; set; } = "";

    /// <summary>覆核後之最終欄位 JSON(與 ResultJson 差異即人工修正內容)</summary>
    public string? ReviewedJson { get; set; }

    [MaxLength(100)]
    public string? ModelName { get; set; }

    public ReviewStatus ReviewStatus { get; set; } = ReviewStatus.Pending;
    public Guid? ReviewedById { get; set; }
    public DateTime? ReviewedAt { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
