using System.Text.Json;
using Dmat.Web.Data;
using Dmat.Web.Hubs;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services.Ocr;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.SignalR;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

public class ReviewFieldVm
{
    public required FieldDef Def { get; init; }
    public string? Value { get; set; }
    public bool Checked { get; set; }
    public double? Confidence { get; set; }
    public bool NeedReview { get; set; }
}

public class ReviewDetailVm
{
    public Guid ImageId { get; set; }
    public string? ModelName { get; set; }
    public bool IsManualFallback { get; set; }
    public List<string> Warnings { get; set; } = [];
    public List<ReviewFieldVm> Fields { get; set; } = [];

    /// <summary>產生此結果的是模擬引擎 → 欄位為樣張假資料,不可直接覆核送出。</summary>
    public bool IsMockResult { get; set; }

    /// <summary>仍在背景辨識佇列中(尚未有結果或結果將被覆寫)。</summary>
    public bool IsAnalyzing { get; set; }

    /// <summary>目前 AI 服務/引擎狀態,供介面顯示與判斷是否可重新辨識。</summary>
    public OcrHealth? OcrHealth { get; set; }

    /// <summary>已辨識出值的欄位數(供介面快速判斷辨識覆蓋率)。</summary>
    public int RecognisedCount => Fields.Count(f =>
        f.Def.Kind == FieldKind.Checkbox ? f.Checked : !string.IsNullOrWhiteSpace(f.Value));

    public int NeedReviewCount => Fields.Count(f => f.NeedReview);

    public IEnumerable<IGrouping<string, ReviewFieldVm>> Groups => Fields.GroupBy(f => f.Def.Group);
}

/// <summary>
/// AI 辨識工作流程模組之覆核部分(架構書 4.1 步驟 4):
/// 覆核佇列、覆核介面資料、確認後寫入傷患主檔與檢傷紀錄。
/// </summary>
public class ReviewService(
    DmatDbContext db,
    AuditService audit,
    IDataProtectionProvider dataProtection,
    IHubContext<DashboardHub> dashboardHub,
    DashboardService dashboardService)
{
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    /// <summary>
    /// 覆核佇列。含尚在辨識中的影像(Queued/Recognizing)——
    /// 辨識改為背景處理後,上傳完到辨識完之間有一段空窗;若不顯示,
    /// 現場會以為照片沒傳上去而重拍。
    /// </summary>
    public Task<List<RecordImage>> GetQueueAsync() =>
        db.RecordImages
            .Where(i => i.Status == RecordImageStatus.Queued
                     || i.Status == RecordImageStatus.Recognizing
                     || i.Status == RecordImageStatus.PendingReview
                     || i.Status == RecordImageStatus.ManualFallback)
            .OrderBy(i => i.UploadedAt)
            .ToListAsync();

    public async Task<ReviewDetailVm?> GetDetailAsync(Guid imageId)
    {
        var image = await db.RecordImages.Include(i => i.OcrResult).FirstOrDefaultAsync(i => i.ImageId == imageId);
        if (image is null) return null;

        OcrAnalyzeResult? ocr = image.OcrResult is null
            ? null
            : JsonSerializer.Deserialize<OcrAnalyzeResult>(image.OcrResult.ResultJson, JsonOpts);

        var vm = new ReviewDetailVm
        {
            ImageId = image.ImageId,
            ModelName = image.OcrResult?.ModelName,
            IsManualFallback = image.Status == RecordImageStatus.ManualFallback,
            Warnings = ocr?.Warnings ?? [],
            IsMockResult = ocr?.IsMock ?? false,
            IsAnalyzing = image.Status is RecordImageStatus.Queued or RecordImageStatus.Recognizing,
        };

        foreach (var def in FieldCatalog.All)
        {
            var f = new ReviewFieldVm { Def = def };
            if (ocr is not null && ocr.Fields.TryGetValue(def.Key, out var ocrField))
            {
                f.Value = ocrField.AsString;
                f.Checked = ocrField.AsBool;
                f.Confidence = ocrField.Confidence;
                f.NeedReview = ocrField.NeedReview;
            }
            else
            {
                // AI 降級(人工輸入模式)或欄位缺漏:全欄位視為待確認
                f.NeedReview = true;
            }
            vm.Fields.Add(f);
        }
        return vm;
    }

    /// <summary>
    /// 覆核確認:依表單值寫入傷患主檔、檢傷紀錄、病史與診斷。
    /// 傷票編號已存在時視為同一傷患之複檢/補頁,新增檢傷紀錄並更新空缺欄位(附錄 B.3 多頁關聯)。
    /// </summary>
    public async Task<(Guid PatientId, string? DuplicateTagWarning)> ConfirmAsync(
        Guid imageId, IFormCollection form, Guid? reviewerId)
    {
        var image = await db.RecordImages.Include(i => i.OcrResult).FirstAsync(i => i.ImageId == imageId);

        string? Get(string key) =>
            form.TryGetValue("f_" + key, out var v) && !string.IsNullOrWhiteSpace(v) ? v.ToString().Trim() : null;
        bool GetBool(string key) => form.TryGetValue("f_" + key, out var v) && v.Contains("true");
        short? GetShort(string key) => short.TryParse(Get(key), out var n) ? n : null;

        // ---- 傷患主檔(依 TagNo upsert) ----
        var tagNo = Get(OcrFieldKeys.PatientTagId);
        string? duplicateWarning = null;
        var patient = tagNo is null
            ? null
            : await db.Patients.Include(p => p.PastHistory).FirstOrDefaultAsync(p => p.TagNo == tagNo);
        if (patient is null)
        {
            patient = new Patient { TagNo = tagNo };
            db.Patients.Add(patient);
        }
        else
        {
            duplicateWarning = $"傷票編號 {tagNo} 已存在,本次覆核已併入同一傷患(新增複檢紀錄)。";
        }

        patient.Name = Get(OcrFieldKeys.PatientName) ?? patient.Name;
        patient.Gender = Get(OcrFieldKeys.Gender) switch
        {
            "男" => Models.Entities.Gender.Male,
            "女" => Models.Entities.Gender.Female,
            "其他" => Models.Entities.Gender.Other,
            _ => patient.Gender,
        };
        patient.EstAge = GetShort(OcrFieldKeys.PatientAge) ?? patient.EstAge;
        if (int.TryParse(Get(OcrFieldKeys.BirthYear), out var by)
            && int.TryParse(Get(OcrFieldKeys.BirthMonth), out var bm)
            && int.TryParse(Get(OcrFieldKeys.BirthDay), out var bd)
            && by is > 1900 and < 2100 && bm is >= 1 and <= 12 && bd is >= 1 and <= 31)
        {
            try { patient.BirthDate = new DateOnly(by, bm, bd); } catch (ArgumentOutOfRangeException) { }
        }
        patient.Nationality = Get(OcrFieldKeys.Nationality) ?? patient.Nationality;
        patient.PresentIllness = Get(OcrFieldKeys.PresentIllness) ?? patient.PresentIllness;

        // 身分證字號:高敏感欄位,加密後儲存(架構書 8.3)
        if (Get(OcrFieldKeys.NationalId) is { } nationalId)
        {
            var protector = dataProtection.CreateProtector("Dmat.NationalId");
            patient.NationalIdEncrypted = protector.Protect(nationalId);
        }

        var triageRaw = Get(OcrFieldKeys.Triage) ?? "3";
        var triageLevel = triageRaw switch
        {
            "1" => TriageLevel.Red,
            "2" => TriageLevel.Yellow,
            "3" => TriageLevel.Green,
            "4" => TriageLevel.Black,
            "4-1" => TriageLevel.Palliative,
            _ => TriageLevel.Green,
        };
        patient.CurrentTriage = triageLevel;
        if (triageLevel == TriageLevel.Black) patient.Status = PatientStatus.Deceased;
        patient.UpdatedAt = DateTime.UtcNow;

        // ---- 檢傷紀錄(每次覆核新增一筆,保留歷程) ----
        var temp = decimal.TryParse(Get(OcrFieldKeys.TemperatureC), out var t) ? t : (decimal?)null;
        db.TriageRecords.Add(new TriageRecord
        {
            Patient = patient,
            Level = triageLevel,
            Consciousness = Get(OcrFieldKeys.Consciousness),
            Temp = temp,
            Sbp = GetShort(OcrFieldKeys.Sbp),
            Dbp = GetShort(OcrFieldKeys.Dbp),
            Hr = GetShort(OcrFieldKeys.Pulse),
            Rr = GetShort(OcrFieldKeys.RespiratoryRate),
            SpO2 = GetShort(OcrFieldKeys.SpO2),
            TriagedById = reviewerId,
        });

        // ---- 過去病史 ----
        var history = patient.PastHistory ?? new PastHistory { Patient = patient };
        history.Pregnant = GetBool(OcrFieldKeys.Pregnant) ? true : history.Pregnant;
        history.VaccineTetanus = GetBool(OcrFieldKeys.VaccineTetanus);
        history.VaccineOther = GetBool(OcrFieldKeys.VaccineOther);
        history.VaccineOtherNote = Get(OcrFieldKeys.VaccineOtherNote);
        history.HasAllergy = GetBool(OcrFieldKeys.HasAllergy);
        history.AllergyNote = Get(OcrFieldKeys.AllergyNote);
        bool[] chronic = OcrFieldKeys.ChronicKeys.Select(GetBool).ToArray();
        history.ChronicDiabetes = chronic[0];
        history.ChronicHypertension = chronic[1];
        history.ChronicDialysis = chronic[2];
        history.ChronicHeartFailure = chronic[3];
        history.ChronicAsthma = chronic[4];
        history.ChronicCopd = chronic[5];
        history.ChronicOther = chronic[6];
        history.ChronicOtherNote = Get(OcrFieldKeys.ChronicOtherNote);
        if (patient.PastHistory is null) db.PastHistories.Add(history);

        // ---- 主要初步診斷(複選;同一傷患不重複寫入相同代碼) ----
        var codes = await db.DiagnosisCodes.ToListAsync();
        var existingCodeIds = patient.PatientId == Guid.Empty
            ? []
            : (await db.DiagnosisRecords.Where(d => d.PatientId == patient.PatientId)
                .Select(d => d.DiagnosisCodeId).ToListAsync()).ToHashSet();
        void AddDiagnoses(string[] keys, byte category, string? note)
        {
            for (var i = 0; i < keys.Length; i++)
            {
                if (!GetBool(keys[i])) continue;
                var code = codes.First(c => c.Category == category && c.ItemNo == i + 1);
                if (existingCodeIds.Contains(code.DiagnosisCodeId)) continue;
                db.DiagnosisRecords.Add(new DiagnosisRecord
                {
                    Patient = patient,
                    DiagnosisCodeId = code.DiagnosisCodeId,
                    Note = code.NameZh.StartsWith("其他") ? note : null,
                });
            }
        }
        AddDiagnoses(OcrFieldKeys.TraumaKeys, category: 1, note: null);
        AddDiagnoses(OcrFieldKeys.NonTraumaKeys, category: 2, note: Get(OcrFieldKeys.NonTraumaOtherNote));

        // ---- 覆核結果與稽核 ----
        image.PatientId = patient.PatientId;
        image.Status = RecordImageStatus.Committed;
        if (image.OcrResult is { } ocr)
        {
            var reviewedFields = FieldCatalog.All.ToDictionary(
                d => d.Key,
                d => d.Kind == FieldKind.Checkbox ? (object)GetBool(d.Key) : Get(d.Key) ?? "");
            ocr.ReviewedJson = JsonSerializer.Serialize(reviewedFields, JsonOpts);
            var original = JsonSerializer.Deserialize<OcrAnalyzeResult>(ocr.ResultJson, JsonOpts);
            var corrected = original is not null && FieldCatalog.All.Any(d =>
            {
                var orig = original.Fields.GetValueOrDefault(d.Key);
                return d.Kind == FieldKind.Checkbox
                    ? (orig?.AsBool ?? false) != GetBool(d.Key)
                    : (orig?.AsString ?? "") != (Get(d.Key) ?? "");
            });
            ocr.ReviewStatus = corrected ? ReviewStatus.Corrected : ReviewStatus.Confirmed;
            ocr.ReviewedById = reviewerId;
            ocr.ReviewedAt = DateTime.UtcNow;
        }

        audit.Log("ReviewConfirm", nameof(Patient), patient.PatientId.ToString(),
            $"imageId={imageId} tagNo={tagNo}");

        // 【預留】中央同步:記錄異動範圍供網路恢復後批次上傳(架構書 7.6)
        db.SyncLogs.Add(new SyncLog { TableName = nameof(Patient), RecordId = patient.PatientId.ToString() });

        await db.SaveChangesAsync();

        // 資料異動觸發儀表板統計更新,SignalR 即時推播(架構書 4.1 步驟 5)
        var summary = await dashboardService.GetSummaryAsync();
        await dashboardHub.Clients.All.SendAsync("summaryUpdated", summary);

        return (patient.PatientId, duplicateWarning);
    }
}
