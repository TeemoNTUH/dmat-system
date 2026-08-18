using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

/// <summary>操作結果。<c>Error</c> 有值代表未寫入。</summary>
public record CareResult(string? Message, string? Error = null)
{
    public bool Succeeded => Error is null;

    public static CareResult Fail(string error) => new(null, error);
}

/// <summary>
/// 覆核之後的傷患照護異動:動向狀態、基本資料修正、現場重新檢傷。
///
/// **為什麼這三件事要獨立於覆核流程**
///
/// 覆核(<see cref="ReviewService.ConfirmAsync"/>)是「把紙本影像的內容登錄進系統」,
/// 一張影像只走一次。但傷患進站後的狀況會持續變化:病情惡化要重新檢傷、
/// 後送車來了要更新動向、OCR 把傷票編號讀錯要更正。這些都不該逼使用者
/// 重拍一張紙本或刪掉整位傷患重來 —— 前者在現場做不到,後者會連病歷憑證一起毀掉。
///
/// **共同原則**
///
/// - 每次異動都寫 AuditLog。傷患資料的每一次改動都要能追溯是誰在何時改的(架構書 8.4)。
/// - 一律「新增」而非「覆寫」臨床歷程:重新檢傷是新增一筆 TriageRecord,
///   舊紀錄完整保留。事後檢討需要看到病情的變化軌跡,而不只是最後狀態。
/// - 呼叫端負責推播儀表板(架構書 4.2)。
/// </summary>
public class PatientCareService(
    DmatDbContext db,
    AuditService audit,
    IDataProtectionProvider dataProtection,
    ILogger<PatientCareService> logger)
{
    // -----------------------------------------------------------------------
    // 動向狀態
    // -----------------------------------------------------------------------
    public static string StatusLabel(PatientStatus s) => s switch
    {
        PatientStatus.InCare => "收治中",
        PatientStatus.AwaitingEvacuation => "待後送",
        PatientStatus.Evacuating => "後送中",
        PatientStatus.Departed => "離站",
        PatientStatus.Deceased => "死亡",
        _ => "未知",
    };

    /// <summary>
    /// 更新傷患動向。
    ///
    /// **「死亡」與檢傷分類的一致性**:兩者代表同一件事,分開存會讓儀表板
    /// 出現「死亡 3 人、黑標 1 人」這種互相矛盾的數字,指揮官無從判斷哪個是真的。
    /// 因此標記死亡時同步把檢傷分類改為黑標,並補一筆檢傷紀錄留下時間點;
    /// 反之從死亡改回其他狀態時不自動改分類 —— 那種情形極罕見,
    /// 應由人明確地重新檢傷,不該由系統猜。
    /// </summary>
    public async Task<CareResult> UpdateStatusAsync(
        Guid patientId, PatientStatus status, Guid? actorId, CancellationToken ct = default)
    {
        var patient = await db.Patients.FirstOrDefaultAsync(p => p.PatientId == patientId, ct);
        if (patient is null) return CareResult.Fail("查無此傷患,可能已被刪除。");

        var previous = patient.Status;
        if (previous == status)
            return new CareResult($"動向未變更(仍為{StatusLabel(status)})。");

        patient.Status = status;
        patient.UpdatedAt = DateTime.UtcNow;

        var extra = "";
        if (status == PatientStatus.Deceased && patient.CurrentTriage != TriageLevel.Black)
        {
            patient.CurrentTriage = TriageLevel.Black;
            db.TriageRecords.Add(new TriageRecord
            {
                PatientId = patient.PatientId,
                Level = TriageLevel.Black,
                TriagedById = actorId,
            });
            extra = ",檢傷分類同步改為黑標";
        }

        audit.Log("PatientStatusChange", nameof(Patient), patientId.ToString(),
            $"{StatusLabel(previous)} → {StatusLabel(status)}{extra}");
        await db.SaveChangesAsync(ct);

        logger.LogInformation("傷患 {TagNo} 動向 {From} → {To}",
            patient.TagNo, StatusLabel(previous), StatusLabel(status));
        return new CareResult($"已將動向更新為「{StatusLabel(status)}」{extra}。");
    }

    // -----------------------------------------------------------------------
    // 基本資料修正
    // -----------------------------------------------------------------------
    public record PatientEdit(
        string? TagNo,
        string? Name,
        Gender? Gender,
        short? EstAge,
        DateOnly? BirthDate,
        string? NationalId,
        string? Nationality,
        string? PresentIllness);

    /// <summary>
    /// 修正傷患基本資料。
    ///
    /// **傷票編號可以改,但必須唯一。** OCR 把手寫編號讀錯是最常見的錯誤之一,
    /// 而編號是多頁紀錄單併檔的依據(附錄 B.3)—— 改錯會把兩位傷患的資料合在一起,
    /// 所以這裡擋下與他人重複的編號,而不是讓它寫進去之後才發現。
    ///
    /// 空字串一律視為「清空該欄」,與 null 同義:現場想把 OCR 誤讀的內容刪掉時,
    /// 送出的就是空字串,若當成「未修改」使用者會發現怎麼刪都刪不掉。
    /// </summary>
    public async Task<CareResult> UpdateDetailsAsync(
        Guid patientId, PatientEdit edit, CancellationToken ct = default)
    {
        var patient = await db.Patients.FirstOrDefaultAsync(p => p.PatientId == patientId, ct);
        if (patient is null) return CareResult.Fail("查無此傷患,可能已被刪除。");

        var tagNo = Blank(edit.TagNo);
        if (tagNo is not null && tagNo != patient.TagNo)
        {
            var taken = await db.Patients
                .AnyAsync(p => p.TagNo == tagNo && p.PatientId != patientId, ct);
            if (taken)
                return CareResult.Fail(
                    $"傷票編號 {tagNo} 已被其他傷患使用。編號是多頁紀錄單併檔的依據,不可重複。");
        }

        var changes = new List<string>();
        void Track(string field, object? from, object? to)
        {
            var a = from?.ToString() ?? "(空)";
            var b = to?.ToString() ?? "(空)";
            if (a != b) changes.Add($"{field} {a}→{b}");
        }

        Track("傷票編號", patient.TagNo, tagNo);
        Track("姓名", patient.Name, Blank(edit.Name));
        Track("性別", patient.Gender, edit.Gender);
        Track("年齡", patient.EstAge, edit.EstAge);
        Track("生日", patient.BirthDate, edit.BirthDate);
        Track("國籍", patient.Nationality, Blank(edit.Nationality));
        Track("現病史", Snip(patient.PresentIllness), Snip(Blank(edit.PresentIllness)));

        patient.TagNo = tagNo;
        patient.Name = Blank(edit.Name);
        patient.Gender = edit.Gender;
        patient.EstAge = edit.EstAge;
        patient.BirthDate = edit.BirthDate;
        patient.Nationality = Blank(edit.Nationality);
        patient.PresentIllness = Blank(edit.PresentIllness);

        // 身分證字號單獨處理:欄位是加密儲存的,無法比對「有沒有變」,
        // 因此留空一律視為「不動」而非「清空」—— 遮罩顯示的欄位若把空白當成刪除,
        // 使用者只是沒填就會把既有資料洗掉。要清空需明確送出「-」。
        if (Blank(edit.NationalId) is { } nid)
        {
            if (nid == "-")
            {
                patient.NationalIdEncrypted = null;
                changes.Add("身分證字號 已清空");
            }
            else
            {
                patient.NationalIdEncrypted = dataProtection
                    .CreateProtector("Dmat.NationalId").Protect(nid);
                changes.Add("身分證字號 已更新");
            }
        }

        if (changes.Count == 0) return new CareResult("沒有任何欄位變更。");

        patient.UpdatedAt = DateTime.UtcNow;
        audit.Log("PatientEdit", nameof(Patient), patientId.ToString(), string.Join(";", changes));
        await db.SaveChangesAsync(ct);

        logger.LogInformation("修正傷患 {PatientId} 基本資料:{Changes}", patientId, string.Join(";", changes));
        return new CareResult($"已更新 {changes.Count} 個欄位。");
    }

    // -----------------------------------------------------------------------
    // 現場重新檢傷
    // -----------------------------------------------------------------------
    public record RetriageInput(
        TriageLevel Level,
        string? Consciousness,
        decimal? Temp,
        short? Sbp,
        short? Dbp,
        short? Hr,
        short? Rr,
        short? SpO2);

    /// <summary>
    /// 新增一筆檢傷紀錄(複檢),並更新傷患目前的檢傷分類。
    ///
    /// 病情在站內惡化或好轉時,現場需要就地重新檢傷 —— 沒有這條路徑的話,
    /// 唯一的辦法是重填一張紙本再拍一次,那在大量傷患現場不切實際,
    /// 結果就是儀表板上的檢傷分佈停留在入站當下,失去即時性。
    ///
    /// 舊紀錄一律保留:事後檢討要看的是病情變化的軌跡。
    /// </summary>
    public async Task<CareResult> RetriageAsync(
        Guid patientId, RetriageInput input, Guid? actorId, CancellationToken ct = default)
    {
        var patient = await db.Patients.FirstOrDefaultAsync(p => p.PatientId == patientId, ct);
        if (patient is null) return CareResult.Fail("查無此傷患,可能已被刪除。");

        if (input.Sbp is { } sbp && input.Dbp is { } dbp && sbp <= dbp)
            return CareResult.Fail("血壓收縮壓必須大於舒張壓,請確認數值。");

        var previous = patient.CurrentTriage;
        db.TriageRecords.Add(new TriageRecord
        {
            PatientId = patient.PatientId,
            Level = input.Level,
            Consciousness = Blank(input.Consciousness),
            Temp = input.Temp,
            Sbp = input.Sbp,
            Dbp = input.Dbp,
            Hr = input.Hr,
            Rr = input.Rr,
            SpO2 = input.SpO2,
            TriagedById = actorId,
        });

        patient.CurrentTriage = input.Level;
        // 與 ConfirmAsync 一致:黑標即死亡,兩者不可各自為政(見 UpdateStatusAsync)
        if (input.Level == TriageLevel.Black) patient.Status = PatientStatus.Deceased;
        patient.UpdatedAt = DateTime.UtcNow;

        audit.Log("PatientRetriage", nameof(Patient), patientId.ToString(),
            $"{TriageName(previous)} → {TriageName(input.Level)}");
        await db.SaveChangesAsync(ct);

        logger.LogInformation("傷患 {TagNo} 重新檢傷 {From} → {To}",
            patient.TagNo, TriageName(previous), TriageName(input.Level));

        var note = previous == input.Level ? "" : $"(由{TriageName(previous)}改為{TriageName(input.Level)})";
        return new CareResult($"已新增一筆檢傷紀錄{note}。");
    }

    public static string TriageName(TriageLevel level) => level switch
    {
        TriageLevel.Red => "紅・復甦急救",
        TriageLevel.Yellow => "黃・緊急",
        TriageLevel.Green => "綠・非緊急",
        TriageLevel.Black => "黑・死亡",
        TriageLevel.Palliative => "紫・緩和治療",
        _ => "未知",
    };

    // -----------------------------------------------------------------------
    /// <summary>空白字串視同未填。表單送出的空欄位是 "",不是 null。</summary>
    private static string? Blank(string? s) => string.IsNullOrWhiteSpace(s) ? null : s.Trim();

    private static string? Snip(string? s) =>
        s is null ? null : s.Length <= 20 ? s : s[..20] + "…";
}
