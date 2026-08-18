using System.Security.Claims;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services;
using Dmat.Web.Services.Ocr;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Controllers;

/// <summary>影像擷取模組:拍攝/上傳紀錄單影像(權限:醫護人員、站長,架構書 8.2)</summary>
[Authorize(Roles = $"{RoleNames.Medic},{RoleNames.StationLeader},{RoleNames.Admin}")]
public class CaptureController(
    ImageIntakeService intake,
    OcrClient ocrClient,
    Data.DmatDbContext db,
    IWebHostEnvironment env) : Controller
{
    public async Task<IActionResult> Index()
    {
        ViewBag.OcrHealth = await ocrClient.GetHealthAsync();
        return View();
    }

    /// <summary>接收影像(表單或 PWA 離線佇列補傳皆走此端點)</summary>
    [HttpPost]
    [RequestSizeLimit(20 * 1024 * 1024)]
    public async Task<IActionResult> Upload(IFormFile? file)
    {
        if (file is null || file.Length == 0)
            return BadRequest(new { error = "未收到影像檔案" });

        var userId = Guid.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out var g) ? g : (Guid?)null;
        var result = await intake.IntakeAsync(file, userId);

        return Json(new
        {
            imageId = result.Image.ImageId,
            duplicate = result.IsDuplicate,
            ocrSucceeded = result.OcrSucceeded,
            ocrError = result.OcrError,
            status = result.Image.Status.ToString(),
            reviewUrl = Url.Action("Detail", "Review", new { id = result.Image.ImageId }),
        });
    }

    /// <summary>目前 AI 引擎狀態(前端查詢用,讓「模擬引擎」警示即時反映)</summary>
    [HttpGet]
    public async Task<IActionResult> EngineStatus()
    {
        var health = await ocrClient.GetHealthAsync();
        return Json(new
        {
            reachable = health.Reachable,
            isMock = health.IsMock,
            engine = health.Engine,
            engineReady = health.EngineReady,
            description = health.Description,
        });
    }

    /// <summary>提供覆核介面檢視原始影像</summary>
    [Authorize]
    public async Task<IActionResult> Image(Guid id)
    {
        var image = await db.RecordImages.FirstOrDefaultAsync(i => i.ImageId == id);
        if (image is null) return NotFound();
        // 兩種目錄分隔符都接受:資料庫可能是在另一個作業系統上建立的(見 RecordImagePath)
        var path = RecordImagePath.Resolve(env, image.FilePath);
        if (!System.IO.File.Exists(path))
            return NotFound($"影像檔案不存在:{image.FilePath}");
        return PhysicalFile(path, "image/jpeg");
    }
}
