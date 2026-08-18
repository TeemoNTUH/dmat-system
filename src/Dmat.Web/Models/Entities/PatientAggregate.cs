using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Dmat.Web.Models.Entities;

/// <summary>檢傷分類:1 復甦急救(紅)、2 緊急(黃)、3 非緊急(綠)、4 死亡(黑)、5 緩和治療(紀錄單 4-1)</summary>
public enum TriageLevel : byte { Red = 1, Yellow = 2, Green = 3, Black = 4, Palliative = 5 }

/// <summary>傷患狀態</summary>
public enum PatientStatus : byte { InCare = 1, AwaitingEvacuation = 2, Evacuating = 3, Departed = 4, Deceased = 5 }

/// <summary>性別:1 男、2 女、3 其他</summary>
public enum Gender : byte { Male = 1, Female = 2, Other = 3 }

/// <summary>傷患主檔(架構書 6.2.1)。主鍵採 GUID,避免多站離線建檔衝突。</summary>
public class Patient
{
    public Guid PatientId { get; set; } = Guid.NewGuid();

    /// <summary>檢傷手環/傷票編號,站內唯一</summary>
    [MaxLength(30)]
    public string? TagNo { get; set; }

    /// <summary>姓名(可空,無名氏以代號註記)</summary>
    [MaxLength(50)]
    public string? Name { get; set; }

    public Gender? Gender { get; set; }

    /// <summary>年齡(無法確認時為推估值)</summary>
    public short? EstAge { get; set; }

    public DateOnly? BirthDate { get; set; }

    /// <summary>身分證字號:高敏感欄位,以 Data Protection 加密後儲存,顯示時預設遮罩</summary>
    [MaxLength(200)]
    public string? NationalIdEncrypted { get; set; }

    /// <summary>國籍(非本國籍時填寫)</summary>
    [MaxLength(50)]
    public string? Nationality { get; set; }

    public Guid? StationId { get; set; }
    public Station? Station { get; set; }

    public TriageLevel CurrentTriage { get; set; }
    public PatientStatus Status { get; set; } = PatientStatus.InCare;

    /// <summary>現病史(附錄 B:自由文字;人形圖傷部標記保留於原始影像)</summary>
    public string? PresentIllness { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    public List<TriageRecord> TriageRecords { get; set; } = [];
    public PastHistory? PastHistory { get; set; }
    public List<DiagnosisRecord> Diagnoses { get; set; } = [];
    public List<RecordImage> Images { get; set; } = [];
}

/// <summary>檢傷紀錄(架構書 6.2.2)。每次複檢新增一筆保留歷程。</summary>
public class TriageRecord
{
    public Guid TriageId { get; set; } = Guid.NewGuid();

    public Guid PatientId { get; set; }
    public Patient? Patient { get; set; }

    public TriageLevel Level { get; set; }

    /// <summary>意識狀態,依紀錄單手寫內容(清/聲/痛/無 等)</summary>
    [MaxLength(20)]
    public string? Consciousness { get; set; }

    [Column(TypeName = "decimal(4,1)")]
    public decimal? Temp { get; set; }

    public short? Sbp { get; set; }
    public short? Dbp { get; set; }
    public short? Hr { get; set; }
    public short? Rr { get; set; }
    public short? SpO2 { get; set; }

    /// <summary>昏迷指數(進階評估用,可空)</summary>
    public byte? Gcs { get; set; }

    public DateTime TriagedAt { get; set; } = DateTime.UtcNow;
    public Guid? TriagedById { get; set; }
}

/// <summary>過去重要病史(紀錄單第 5 區,欄位對照 Field_Map)</summary>
public class PastHistory
{
    public Guid PastHistoryId { get; set; } = Guid.NewGuid();

    public Guid PatientId { get; set; }
    public Patient? Patient { get; set; }

    /// <summary>懷孕(未勾選且不適用時保留 null)</summary>
    public bool? Pregnant { get; set; }

    public bool VaccineTetanus { get; set; }
    public bool VaccineOther { get; set; }
    [MaxLength(100)]
    public string? VaccineOtherNote { get; set; }

    public bool? HasAllergy { get; set; }
    [MaxLength(200)]
    public string? AllergyNote { get; set; }

    public bool ChronicDiabetes { get; set; }
    public bool ChronicHypertension { get; set; }
    public bool ChronicDialysis { get; set; }
    public bool ChronicHeartFailure { get; set; }
    public bool ChronicAsthma { get; set; }
    public bool ChronicCopd { get; set; }
    public bool ChronicOther { get; set; }
    [MaxLength(200)]
    public string? ChronicOtherNote { get; set; }
}

/// <summary>診斷代碼字典:創傷 19 項、非創傷 25 項(紀錄單第 7 區)</summary>
public class DiagnosisCode
{
    public int DiagnosisCodeId { get; set; }

    /// <summary>1 創傷、2 非創傷</summary>
    public byte Category { get; set; }

    /// <summary>紀錄單上的項次(1~19 / 1~25)</summary>
    public byte ItemNo { get; set; }

    [MaxLength(50)]
    public string NameZh { get; set; } = "";
}

/// <summary>主要初步診斷(可複選)</summary>
public class DiagnosisRecord
{
    public Guid DiagnosisRecordId { get; set; } = Guid.NewGuid();

    public Guid PatientId { get; set; }
    public Patient? Patient { get; set; }

    public int DiagnosisCodeId { get; set; }
    public DiagnosisCode? DiagnosisCode { get; set; }

    /// <summary>「其他」項之補充文字</summary>
    [MaxLength(200)]
    public string? Note { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
