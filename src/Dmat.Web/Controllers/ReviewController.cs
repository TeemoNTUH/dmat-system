using System.Security.Claims;
using Dmat.Web.Hubs;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services;
using Dmat.Web.Services.Ocr;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.SignalR;

namespace Dmat.Web.Controllers;

/// <summary>AI 辨識結果覆核(權限:醫護人員、站長,架構書 8.2)</summary>
[Authorize(Roles = $"{RoleNames.Medic},{RoleNames.StationLeader},{RoleNames.Admin}")]
public class ReviewController(
    ReviewService reviewService,
    ImageIntakeService intake,
    OcrClient ocrClient,
    PatientDeletionService deletionService,
    DashboardService dashboardService,
    IHubContext<DashboardHub> dashboardHub) : Controller
{
    public async Task<IActionResult> Index() => View(await reviewService.GetQueueAsync());

    public async Task<IActionResult> Detail(Guid id)
    {
        var vm = await reviewService.GetDetailAsync(id);
        if (vm is null) return NotFound();
        vm.OcrHealth = await ocrClient.GetHealthAsync();
        return View(vm);
    }

    /// <summary>
    /// 重新辨識:對同一張已存影像重跑 AI 辨識並覆寫結果。
    /// 換引擎(mock → 真實模型)、調門檻、或 AI 服務先前沒啟動時,不需重新拍照。
    /// </summary>
    [HttpPost, ValidateAntiForgeryToken]
    public async Task<IActionResult> Reanalyze(Guid id)
    {
        var result = await intake.ReanalyzeAsync(id);
        // 辨識由背景服務處理,這裡只回報「是否成功排入」
        TempData["Message"] = result.OcrError is null
            ? "已排入辨識佇列,完成後本頁會自動更新。"
            : $"無法重新辨識:{result.OcrError}";
        return RedirectToAction(nameof(Detail), new { id });
    }

    /// <summary>
    /// 刪除覆核佇列中的單張影像(含辨識結果與磁碟上的照片檔)。
    ///
    /// **權限:站長與系統管理者。** 第一線醫護不可刪除影像 —— 拍歪、拍糊的照片
    /// 重拍一張即可,不必刪;而誤刪別人剛上傳、還沒覆核的紀錄單則會直接損失現場資料。
    /// 已完成覆核的影像由服務層另外擋下(那是傷患病歷的原始憑證)。
    /// </summary>
    [HttpPost, ValidateAntiForgeryToken]
    [Authorize(Roles = $"{RoleNames.StationLeader},{RoleNames.Admin}")]
    public async Task<IActionResult> DeleteImage(Guid id)
    {
        var result = await deletionService.DeleteImageAsync(id);
        TempData["Message"] = result switch
        {
            null => "查無此影像,可能已被刪除。",
            { Succeeded: false } r => $"未刪除:{r.Refused}",
            { } r => $"已刪除影像 {r.HashPrefix}…" + (r.FileDeleted ? "(含照片檔)。" : "(照片檔原本就不存在)。"),
        };

        // 待覆核影像數已改變,推播給所有儀表板(架構書 4.2)
        await dashboardHub.Clients.All.SendAsync("summaryUpdated", await dashboardService.GetSummaryAsync());
        return RedirectToAction(nameof(Index));
    }

    [HttpPost, ValidateAntiForgeryToken]
    public async Task<IActionResult> Confirm(Guid id)
    {
        var reviewerId = Guid.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out var g) ? g : (Guid?)null;
        var (patientId, warning) = await reviewService.ConfirmAsync(id, Request.Form, reviewerId);
        TempData["Message"] = warning ?? "覆核完成,資料已寫入傷患主檔。";
        return RedirectToAction("Detail", "Patients", new { id = patientId });
    }
}
