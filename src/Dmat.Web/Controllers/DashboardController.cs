using Dmat.Web.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Dmat.Web.Controllers;

/// <summary>
/// 儀表板:站內儀表板為全角色可視(架構書 8.2);跨站態勢總覽屬指揮官/管理者,
/// 本切片為單站部署,以站內儀表板呈現。
/// </summary>
[Authorize]
public class DashboardController(DashboardService dashboardService) : Controller
{
    public async Task<IActionResult> Index()
    {
        ViewBag.Recent = await dashboardService.GetRecentPatientsAsync();
        return View(await dashboardService.GetSummaryAsync());
    }

    /// <summary>輪詢備援端點(SignalR 斷線時前端改用此端點,架構書 4.2)</summary>
    [HttpGet]
    public async Task<IActionResult> Summary() => Json(await dashboardService.GetSummaryAsync());
}
