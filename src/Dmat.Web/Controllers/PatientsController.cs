using System.Security.Claims;
using Dmat.Web.Data;
using Dmat.Web.Hubs;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.SignalR;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Controllers;

[Authorize]
public class PatientsController(
    DmatDbContext db,
    IDataProtectionProvider dataProtection,
    PatientDeletionService deletionService,
    PatientCareService careService,
    PatientQueryService queryService,
    DashboardService dashboardService,
    IHubContext<DashboardHub> dashboardHub,
    IWebHostEnvironment env) : Controller
{
    /// <summary>傷患清單:關鍵字/檢傷/動向篩選 + 分頁(見 PatientQueryService)。</summary>
    public async Task<IActionResult> Index(string? q, TriageLevel? triage, PatientStatus? status, int page = 1)
        => View(await queryService.QueryAsync(new PatientFilter(q, triage, status, page)));

    public async Task<IActionResult> Detail(Guid id)
    {
        var patient = await db.Patients
            .Include(p => p.TriageRecords.OrderByDescending(t => t.TriagedAt))
            .Include(p => p.PastHistory)
            .Include(p => p.Diagnoses).ThenInclude(d => d.DiagnosisCode)
            .Include(p => p.Images)
            .FirstOrDefaultAsync(p => p.PatientId == id);
        if (patient is null) return NotFound();

        // 身分證字號預設遮罩顯示(附錄 B.3);完整內容僅授權角色可檢視,本切片一律遮罩
        string? maskedNationalId = null;
        if (patient.NationalIdEncrypted is not null)
        {
            try
            {
                var plain = dataProtection.CreateProtector("Dmat.NationalId").Unprotect(patient.NationalIdEncrypted);
                maskedNationalId = plain.Length > 3 ? plain[..2] + new string('*', plain.Length - 3) + plain[^1] : "***";
            }
            catch { maskedNationalId = "(解密失敗)"; }
        }
        ViewBag.MaskedNationalId = maskedNationalId;

        // 病歷的原始憑證若遺失,是需要讓覆核者看見的資訊,不該只呈現一張破圖。
        // 在此先判斷檔案是否存在,由檢視改以明確的「檔案遺失」方塊呈現。
        ViewBag.MissingImageIds = patient.Images
            .Where(i => !RecordImagePath.Exists(env, i.FilePath))
            .Select(i => i.ImageId)
            .ToHashSet();

        return View(patient);
    }

    // -----------------------------------------------------------------------
    // 覆核之後的照護異動(見 PatientCareService)
    //
    // 權限一律為醫護/站長/系統管理者。**指揮官刻意排除** —— 指揮官看的是全站態勢,
    // 不在床邊,由他改個別傷患的檢傷或動向會與現場實況脫節(架構書 8.2)。
    // -----------------------------------------------------------------------
    private const string CareRoles = $"{RoleNames.Medic},{RoleNames.StationLeader},{RoleNames.Admin}";

    /// <summary>更新動向(收治中/待後送/後送中/離站/死亡)。</summary>
    [HttpPost, ValidateAntiForgeryToken, Authorize(Roles = CareRoles)]
    public Task<IActionResult> UpdateStatus(Guid id, PatientStatus status) =>
        RunAsync(id, () => careService.UpdateStatusAsync(id, status, CurrentUserId));

    /// <summary>修正基本資料(OCR 誤讀、事後補齊)。</summary>
    [HttpPost, ValidateAntiForgeryToken, Authorize(Roles = CareRoles)]
    public Task<IActionResult> Edit(
        Guid id, string? tagNo, string? name, Gender? gender, short? estAge,
        DateOnly? birthDate, string? nationalId, string? nationality, string? presentIllness) =>
        RunAsync(id, () => careService.UpdateDetailsAsync(id, new PatientCareService.PatientEdit(
            tagNo, name, gender, estAge, birthDate, nationalId, nationality, presentIllness)));

    /// <summary>現場重新檢傷:新增一筆檢傷紀錄並更新目前分類。</summary>
    [HttpPost, ValidateAntiForgeryToken, Authorize(Roles = CareRoles)]
    public Task<IActionResult> Retriage(
        Guid id, TriageLevel level, string? consciousness, decimal? temp,
        short? sbp, short? dbp, short? hr, short? rr, short? spO2) =>
        RunAsync(id, () => careService.RetriageAsync(id, new PatientCareService.RetriageInput(
            level, consciousness, temp, sbp, dbp, hr, rr, spO2), CurrentUserId));

    /// <summary>
    /// 三個照護動作的共同收尾:回報訊息、推播儀表板、導回明細。
    ///
    /// 推播不可省略 —— 檢傷分類與動向都是儀表板統計的來源,
    /// 不推播的話指揮官看到的數字會停在上一次覆核,而他無從得知那是舊的。
    /// </summary>
    private async Task<IActionResult> RunAsync(Guid id, Func<Task<CareResult>> action)
    {
        var result = await action();
        TempData["Message"] = result.Error ?? result.Message;
        if (result.Succeeded)
            await dashboardHub.Clients.All.SendAsync("summaryUpdated", await dashboardService.GetSummaryAsync());
        return RedirectToAction(nameof(Detail), new { id });
    }

    private Guid? CurrentUserId =>
        Guid.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out var g) ? g : null;

    /// <summary>
    /// 刪除傷患全部資料(含原始紀錄單影像檔)。
    ///
    /// **限系統管理者**:這是本系統唯一的破壞性操作,醫護/站長/指揮官皆不可執行
    /// (架構書 8.2)。刪除行為會寫入 AuditLog,而 AuditLog 僅增查不可刪改(8.4)——
    /// 資料可以刪,但「誰刪了什麼」的軌跡會留下。
    /// </summary>
    [HttpPost, ValidateAntiForgeryToken]
    [Authorize(Roles = RoleNames.Admin)]
    public async Task<IActionResult> Delete(Guid id, string? returnUrl = null)
    {
        var result = await deletionService.DeleteAsync(id);
        TempData["Message"] = result is null
            ? "查無此傷患,可能已被刪除。"
            : $"已刪除傷患 {result.TagNo}({result.Name ?? "無名氏"})及其所有資料:{result.Describe()}。";

        // 統計已改變,推播給所有儀表板(架構書 4.2)
        await dashboardHub.Clients.All.SendAsync("summaryUpdated", await dashboardService.GetSummaryAsync());

        if (!string.IsNullOrEmpty(returnUrl) && Url.IsLocalUrl(returnUrl))
            return Redirect(returnUrl);
        return RedirectToAction("Index", "Dashboard");
    }
}
