using System.Globalization;
using Dmat.Web.Data;
using Dmat.Web.Hubs;
using Dmat.Web.Models.Entities;
using Dmat.Web.Services;
using Dmat.Web.Services.Ocr;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// 執行期資料目錄(SQLite 檔、影像儲存區、金鑰);SQLite 不會自行建立資料夾
Directory.CreateDirectory(Path.Combine(builder.Environment.ContentRootPath, "app_data"));

// 集中式日誌(架構書 9:Serilog)
builder.Host.UseSerilog((ctx, cfg) => cfg
    .MinimumLevel.Information()
    .WriteTo.Console()
    .WriteTo.File("logs/dmat-.log", rollingInterval: RollingInterval.Day));

// ---- 資料庫提供者切換(架構書 6.3.1) ----
var dbProvider = builder.Configuration["Database:Provider"] ?? "Sqlite";
builder.Services.AddDbContext<DmatDbContext>(opt =>
{
    switch (dbProvider)
    {
        case "Sqlite":
            opt.UseSqlite(builder.Configuration["Database:ConnectionStrings:Sqlite"]);
            break;
        case "SqlServer":
            // 【預留】標準部署採 MS SQL Server:安裝 Microsoft.EntityFrameworkCore.SqlServer
            // 套件並依架構書 6.3.1 建立 Migrations/SqlServer 後,改用 opt.UseSqlServer(...) 啟用。
            throw new NotSupportedException(
                "SqlServer provider 尚未啟用,本切片以 SQLite 為主(架構書 6.3.3 輕量單機模式)。");
        default:
            throw new InvalidOperationException($"未知的資料庫提供者:{dbProvider}");
    }
});

// ---- 身分驗證與授權(架構書 8.1:Identity + Cookie + RBAC) ----
builder.Services.AddIdentity<AppUser, AppRole>(opt =>
{
    opt.Password.RequiredLength = 8;
    opt.Password.RequireNonAlphanumeric = false;
    opt.Lockout.MaxFailedAccessAttempts = 5;
    opt.Lockout.DefaultLockoutTimeSpan = TimeSpan.FromMinutes(15);
}).AddEntityFrameworkStores<DmatDbContext>();

builder.Services.ConfigureApplicationCookie(opt =>
{
    opt.LoginPath = "/Account/Login";
    opt.AccessDeniedPath = "/Account/Denied";
});

// 身分證字號加密之金鑰保存於本地(離線環境,無外部金鑰服務)
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(Path.Combine(builder.Environment.ContentRootPath, "app_data", "keys")));

// 多語系【預留】:介面文字先以 zh-TW 直接撰寫,Resources/ 結構與管線已就緒
builder.Services.AddLocalization(opt => opt.ResourcesPath = "Resources");

builder.Services.AddControllersWithViews();
builder.Services.AddSignalR();
builder.Services.AddHttpContextAccessor();

// ---- 應用服務層 ----
builder.Services.AddHttpClient<OcrClient>((sp, http) =>
{
    var cfg = sp.GetRequiredService<IConfiguration>();
    http.BaseAddress = new Uri(cfg["AiService:BaseUrl"] ?? "http://localhost:8100");
    http.Timeout = TimeSpan.FromSeconds(cfg.GetValue("AiService:TimeoutSeconds", 120));
});
// 辨識工作佇列為單例(跨請求共用),背景服務負責消化(架構書 4.1 非同步化)
builder.Services.AddSingleton<OcrJobQueue>();
builder.Services.AddHostedService<OcrBackgroundWorker>();
builder.Services.AddScoped<ImageIntakeService>();
builder.Services.AddScoped<ReviewService>();
builder.Services.AddScoped<PatientDeletionService>();
builder.Services.AddScoped<PatientCareService>();
builder.Services.AddScoped<PatientQueryService>();
builder.Services.AddScoped<DashboardService>();
builder.Services.AddScoped<AuditService>();

var app = builder.Build();

// 啟動時套用 Migrations 與種子資料;SQLite 啟用 WAL 模式(架構書 6.3.2)
using (var scope = app.Services.CreateScope())
{
    await DbSeeder.SeedAsync(scope.ServiceProvider);
    if (dbProvider == "Sqlite")
    {
        var db = scope.ServiceProvider.GetRequiredService<DmatDbContext>();
        await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode=WAL;");
    }
}

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
}

// 離線區網環境:HTTPS 由反向代理/內部 CA 處理(架構書 8.3、Q11),開發階段以 HTTP 運行

var supportedCultures = new[] { new CultureInfo("zh-TW") };
app.UseRequestLocalization(new RequestLocalizationOptions
{
    DefaultRequestCulture = new("zh-TW"),
    SupportedCultures = supportedCultures,
    SupportedUICultures = supportedCultures,
});

app.UseStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();

app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}");
app.MapHub<DashboardHub>("/hubs/dashboard");

app.Run();
