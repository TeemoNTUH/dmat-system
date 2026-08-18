using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace Dmat.Web.Hubs;

/// <summary>
/// 儀表板即時推播(架構書 3.2/4.2)。伺服器端於資料異動後推送 summaryUpdated;
/// 前端另有輪詢備援(dashboard.js),SignalR 斷線期間仍可更新。
/// </summary>
[Authorize]
public class DashboardHub : Hub;
