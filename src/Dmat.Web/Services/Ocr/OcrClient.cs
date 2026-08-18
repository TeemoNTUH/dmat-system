using System.Text.Json;
using System.Text.Json.Serialization;

namespace Dmat.Web.Services.Ocr;

/// <summary>AI 服務健康狀態(架構書 5.2 /api/v1/health)。</summary>
public class OcrHealth
{
    [JsonPropertyName("status")] public string Status { get; set; } = "";
    [JsonPropertyName("engine")] public string Engine { get; set; } = "";
    [JsonPropertyName("engineKey")] public string EngineKey { get; set; } = "";

    /// <summary>true 表示目前為模擬引擎,辨識結果為樣張假資料、與上傳影像無關。</summary>
    [JsonPropertyName("isMock")] public bool IsMock { get; set; }

    [JsonPropertyName("engineReady")] public bool EngineReady { get; set; }
    [JsonPropertyName("error")] public string? Error { get; set; }

    /// <summary>連線不到 AI 服務時為 false。</summary>
    [JsonIgnore] public bool Reachable { get; set; } = true;

    /// <summary>可直接顯示於介面的狀態說明。</summary>
    [JsonIgnore]
    public string Description => !Reachable
        ? "無法連線至 AI 辨識服務"
        : Error is not null ? Error
        : IsMock ? $"模擬引擎({Engine})"
        : EngineReady ? Engine
        : $"{Engine}(推論後端尚未就緒)";
}

/// <summary>辨識呼叫結果:成功帶 Result,失敗帶可顯示給覆核人員的 Error。</summary>
public record OcrAttempt(OcrAnalyzeResult? Result, string? Error)
{
    public bool Succeeded => Result is not null;
    public static OcrAttempt Ok(OcrAnalyzeResult r) => new(r, null);
    public static OcrAttempt Fail(string reason) => new(null, reason);
}

/// <summary>
/// AI 辨識服務客戶端(架構書 5.2 REST 介面)。
/// 失效時由呼叫端降級為人工輸入模式(架構書 5.3);正式版可再加上斷路器(Polly)。
/// </summary>
public class OcrClient(HttpClient http, ILogger<OcrClient> logger)
{
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    /// <summary>
    /// 上傳影像執行 OCR + NLP 結構化。
    /// 失敗時回傳失敗原因而非只回 null — 讓覆核人員知道是「服務沒開」還是「模型看不懂這張」,
    /// 否則畫面上只會出現一片空白欄位,無從排除問題。
    /// </summary>
    public async Task<OcrAttempt> AnalyzeAsync(
        Stream imageStream, string fileName, CancellationToken ct = default)
    {
        try
        {
            using var content = new MultipartFormDataContent();
            var filePart = new StreamContent(imageStream);
            filePart.Headers.ContentType = new("image/jpeg");
            content.Add(filePart, "file", fileName);

            var resp = await http.PostAsync("/api/v1/ocr/analyze", content, ct);
            var json = await resp.Content.ReadAsStringAsync(ct);

            if (!resp.IsSuccessStatusCode)
            {
                var reason = TryReadError(json) ?? $"AI 服務回傳 HTTP {(int)resp.StatusCode}";
                logger.LogWarning("AI 辨識失敗:{Reason}", reason);
                return OcrAttempt.Fail(reason);
            }

            var result = JsonSerializer.Deserialize<OcrAnalyzeResult>(json, JsonOpts);
            if (result is null || result.Fields.Count == 0)
                return OcrAttempt.Fail("AI 服務回傳空白結果(未取得任何欄位)");

            return OcrAttempt.Ok(result);
        }
        catch (TaskCanceledException) when (!ct.IsCancellationRequested)
        {
            const string reason = "AI 辨識逾時。大張影像或首次載入模型較慢,可調高 AiService:TimeoutSeconds 後重新辨識。";
            logger.LogWarning(reason);
            return OcrAttempt.Fail(reason);
        }
        catch (HttpRequestException ex)
        {
            var reason = $"無法連線至 AI 辨識服務({http.BaseAddress}):{ex.Message}";
            logger.LogWarning(ex, "AI 辨識服務呼叫失敗,將降級為人工輸入模式");
            return OcrAttempt.Fail(reason);
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "AI 辨識服務呼叫失敗,將降級為人工輸入模式");
            return OcrAttempt.Fail($"AI 辨識發生錯誤:{ex.Message}");
        }
    }

    /// <summary>查詢 AI 服務與推論引擎狀態(供介面顯示「目前是模擬還是真實辨識」)。</summary>
    public async Task<OcrHealth> GetHealthAsync(CancellationToken ct = default)
    {
        try
        {
            var resp = await http.GetAsync("/api/v1/health", ct);
            var json = await resp.Content.ReadAsStringAsync(ct);
            var health = JsonSerializer.Deserialize<OcrHealth>(json, JsonOpts) ?? new OcrHealth();
            health.Reachable = true;
            if (!resp.IsSuccessStatusCode && health.Error is null)
                health.Error = $"AI 服務回報異常(HTTP {(int)resp.StatusCode})";
            return health;
        }
        catch (Exception ex)
        {
            logger.LogDebug(ex, "AI 服務健康檢查失敗");
            return new OcrHealth { Reachable = false, Status = "unreachable" };
        }
    }

    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
        => (await GetHealthAsync(ct)).Reachable;

    /// <summary>AI 服務失敗時以 {"error": "…"} 或 {"detail": "…"} 回傳原因。</summary>
    private static string? TryReadError(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            // 空白字串視同「沒有訊息」,讓呼叫端退回顯示 HTTP 狀態碼。
            // 回傳空字串的話,畫面會出現「AI 辨識失敗:」後面什麼都沒有 ——
            // 那比直接說「HTTP 500」更沒有幫助。
            if (doc.RootElement.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.String)
                return Blank(e.GetString());
            if (doc.RootElement.TryGetProperty("detail", out var d))
                return Blank(d.ValueKind == JsonValueKind.String ? d.GetString() : d.GetRawText());
        }
        catch (JsonException) { }
        return null;

        static string? Blank(string? v) => string.IsNullOrWhiteSpace(v) ? null : v;
    }
}
