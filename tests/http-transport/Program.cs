using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using ArcGISProMCP.Bridge;

// Real transport and schemas, fake GIS dispatcher. No installed add-in is changed.
const string TestAuthorization = "Bearer TEST-ONLY"; // Synthetic test credential, never used by production.
using var server = new McpHttpServer(value => value == TestAuthorization);
var dispatched = 0;
CommandRouter.Register("get_project_info", "test", "test", _ => { dispatched++; return new { name = "stub-project" }; });
CommandRouter.Register("rename_layer", "test", "test", _ => { dispatched++; return new { renamed = true }; });
server.Start(16520);
using var http = new HttpClient { BaseAddress = new Uri("http://127.0.0.1:16520/"), Timeout = TimeSpan.FromSeconds(10) };
http.DefaultRequestHeaders.Accept.ParseAdd("application/json, text/event-stream");
http.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", TestAuthorization);
var id = 0;
async Task<JsonElement> Call(string method, object parameters)
{
    var current = ++id;
    using var response = await http.PostAsJsonAsync("mcp", new { jsonrpc = "2.0", id = current, method, @params = parameters });
    response.EnsureSuccessStatusCode();
    if (response.Content.Headers.ContentType?.MediaType != "application/json") throw new Exception("Incorrect content type");
    var body = await response.Content.ReadFromJsonAsync<JsonElement>();
    if (body.GetProperty("id").GetInt32() != current) throw new Exception("Incorrect response id");
    return body;
}
var init = await Call("initialize", new { protocolVersion = "2025-03-26", capabilities = new { }, clientInfo = new { name = "test", version = "1" } });
if (init.GetProperty("result").GetProperty("protocolVersion").GetString() != "2025-03-26") throw new Exception("Protocol negotiation");
using var notification = await http.PostAsJsonAsync("mcp", new { jsonrpc = "2.0", method = "notifications/initialized" });
if (notification.StatusCode != HttpStatusCode.Accepted) throw new Exception("Notification status");
await Call("ping", new { });
var list = await Call("tools/list", new { });
var names = list.GetProperty("result").GetProperty("tools").EnumerateArray().Select(t => t.GetProperty("name").GetString()).ToArray();
if (names.Length != 18 || names.Distinct().Count() != names.Length) throw new Exception("Hardened tool catalog");
var result = await Call("tools/call", new { name = "get_project_info", arguments = new { } });
if (!result.GetProperty("result").GetProperty("content")[0].GetProperty("text").GetString().Contains("stub-project")) throw new Exception("Dispatch");
var error = await Call("tools/call", new { name = "missing_tool", arguments = new { } });
if (!error.GetProperty("result").GetProperty("isError").GetBoolean()) throw new Exception("Tool error");
using var get = await http.GetAsync("mcp");
if (get.StatusCode != HttpStatusCode.MethodNotAllowed) throw new Exception("GET must reject unsupported SSE");
using var crossOrigin = new HttpRequestMessage(HttpMethod.Post, "mcp")
{
    Content = JsonContent.Create(new { jsonrpc = "2.0", id = 99, method = "ping" }),
};
crossOrigin.Headers.Add("Origin", "https://attacker.invalid");
using var crossOriginResponse = await http.SendAsync(crossOrigin);
if (crossOriginResponse.StatusCode != HttpStatusCode.Forbidden) throw new Exception("Origin must reject");
using var invalid = await http.PostAsJsonAsync("mcp", new { id = 100, method = "ping" });
if (invalid.StatusCode != HttpStatusCode.OK) throw new Exception("Invalid JSON-RPC response status");
var invalidBody = await invalid.Content.ReadFromJsonAsync<JsonElement>();
if (invalidBody.GetProperty("error").GetProperty("code").GetInt32() != -32600) throw new Exception("JSON-RPC validation");
using var tooLarge = new HttpRequestMessage(HttpMethod.Post, "mcp")
{
    Content = new StringContent(new string('x', 1024 * 1024 + 1)),
};
using var tooLargeResponse = await http.SendAsync(tooLarge);
if (tooLargeResponse.StatusCode != HttpStatusCode.RequestEntityTooLarge) throw new Exception("Request size limit");
using var largeId = await http.PostAsync("mcp", new StringContent(
    "{\"jsonrpc\":\"2.0\",\"id\":9007199254740993,\"method\":\"ping\"}",
    System.Text.Encoding.UTF8, "application/json"));
var largeIdBody = await largeId.Content.ReadFromJsonAsync<JsonElement>();
if (largeIdBody.GetProperty("id").GetRawText() != "9007199254740993") throw new Exception("ID precision");
using var oversizedChunked = await http.PostAsJsonAsync("mcp", new {
    jsonrpc = "2.0", id = 101, method = "ping", padding = new string('x', 1024 * 1024)
});
if (oversizedChunked.StatusCode != HttpStatusCode.RequestEntityTooLarge) throw new Exception("Chunked size limit");
using var wrongContentType = await http.PostAsync("mcp", new StringContent("{}"));
if (wrongContentType.StatusCode != HttpStatusCode.UnsupportedMediaType) throw new Exception("Content type");
foreach (var malformed in new[] { "[]", "null", "{\"jsonrpc\":\"2.0\",\"method\":42,\"id\":1}", "{\"jsonrpc\":\"2.0\",\"method\":\"ping\",\"id\":{}}" })
{
    using var malformedResponse = await http.PostAsync("mcp", new StringContent(malformed, System.Text.Encoding.UTF8, "application/json"));
    var malformedBody = await malformedResponse.Content.ReadFromJsonAsync<JsonElement>();
    if (malformedBody.GetProperty("error").GetProperty("code").GetInt32() != -32600) throw new Exception("Malformed envelope");
}
Console.WriteLine("PASS regressions: chunked JSON, exact large IDs, chunked size limit, content type, malformed envelopes");
Console.WriteLine("PASS HTTP: initialize, notification, ping, 18 policy-filtered tools, dispatch, tool error, GET 405, origin, JSON-RPC, size limit");

using var unauthenticated = new HttpClient { BaseAddress = http.BaseAddress };
foreach (var credential in new string[] { null, "Bearer wrong", TestAuthorization + "junk" })
{
    using var request = new HttpRequestMessage(HttpMethod.Post, "mcp") { Content = JsonContent.Create(new { jsonrpc = "2.0", id = 1, method = "tools/list" }) };
    if (credential != null) request.Headers.TryAddWithoutValidation("Authorization", credential);
    using var response = await unauthenticated.SendAsync(request);
    if (response.StatusCode != HttpStatusCode.Unauthorized) throw new Exception("Authentication must fail closed");
}
async Task Denied(string tool, object arguments)
{
    var before = dispatched;
    var response = await Call("tools/call", new { name = tool, arguments });
    if (!response.GetProperty("result").GetProperty("isError").GetBoolean() || dispatched != before)
        throw new Exception("Denied tool reached dispatcher: " + tool);
}
await Denied("rename_layer", new { layer_name = "test", new_name = "other" });
await Denied("get_features", new { layer_name = "C:\\data.gdb\\secrets" });
await Denied("get_features", new { layer_name = "test", where = "1=1" });
await Denied("get_features", new { layer_name = "test", limit = -1 });
await Denied("get_features", new { layer_name = "test", limit = 1001 });
await Denied("get_features", new { layer_name = "test", offset = int.MaxValue });
await Denied("get_features", new { layer_name = "test", include_geometry = true });
await Denied("get_features", new { layer_name = "test", fields = new[] { "* FROM secrets--" } });
await Denied("get_features", new { layer_name = "test", limit = "10" });
await Denied("get_project_info", new { enable_editing = true });
await Denied("GET_PROJECT_INFO", new { });
await Denied("get_features", new { });
await Denied("get_features", new { layer_name = new string('x', 513) });
await Denied("get_features", new { layer_name = "test", fields = Array.Empty<string>() });
foreach (var raw in new[] {
    "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"get_project_info\",\"name\":\"execute_arcpy_code\"}}",
    "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\",\"params\":[]}" })
{
    using var response = await http.PostAsync("mcp", new StringContent(raw, System.Text.Encoding.UTF8, "application/json"));
    var body = await response.Content.ReadFromJsonAsync<JsonElement>();
    if (!body.TryGetProperty("error", out _)) throw new Exception("Malformed params or duplicate accepted");
}
using (var stream = typeof(ToolPolicy).Assembly.GetManifestResourceStream("ArcGISProMCP.Resources.tools.json"))
using (var catalog = JsonDocument.Parse(stream))
{
    var disabled = 0;
    ToolPolicy.EnableReviewedEditing();
    foreach (var tool in catalog.RootElement.GetProperty("tools").EnumerateArray())
    {
        var name = tool.GetProperty("name").GetString();
        if (ToolPolicy.IsAdvertised(name)) continue;
        await Denied(name, new { });
        disabled++;
    }
    if (disabled != 94) throw new Exception("Disabled tool coverage changed");
}
await Denied("set_layer_visibility", new { visible = false });
await Denied("set_layer_transparency", new { layer_name = "test", transparency = 101 });
var edit = await Call("tools/call", new { name = "rename_layer", arguments = new { layer_name = "test", new_name = "other" } });
if (edit.GetProperty("result").TryGetProperty("isError", out _)) throw new Exception("Explicit local editing grant not honored");
ToolPolicy.RevokeEditing();
await Denied("rename_layer", new { layer_name = "test", new_name = "other" });
var sameProject = true;
ToolPolicy.EnableReviewedEditing(() => sameProject);
sameProject = false;
await Denied("rename_layer", new { layer_name = "test", new_name = "other" });
ToolPolicy.EnableReviewedEditing();
typeof(ToolPolicy).GetField("_editDeadline", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)
    .SetValue(null, Environment.TickCount64 - 1);
await Denied("rename_layer", new { layer_name = "test", new_name = "other" });

// The real router is linked, with only ArcGIS thread marshalling stubbed.
// A queued request must recheck a revoked grant when it reaches the MCT.
ToolPolicy.EnableReviewedEditing();
ArcGIS.Desktop.Framework.Threading.Tasks.QueuedTask.BeforeRun = ToolPolicy.RevokeEditing;
await Denied("rename_layer", new { layer_name = "test", new_name = "other" });
ArcGIS.Desktop.Framework.Threading.Tasks.QueuedTask.BeforeRun = null;

var entered = new TaskCompletionSource();
var release = new TaskCompletionSource();
CommandRouter.RegisterAsync("count_features", "test", "blocking", async _ => { entered.SetResult(); await release.Task; return new { count = 3 }; });
using var argsDoc = JsonDocument.Parse("{\"layer_name\":\"test\"}");
var pending = CommandRouter.DispatchAsync("count_features", new Params(argsDoc.RootElement), argsDoc.RootElement);
await entered.Task;
try { await CommandRouter.DispatchAsync("get_project_info", new Params(default), default); throw new Exception("Concurrent dispatch accepted"); }
catch (InvalidOperationException e) when (e.Message.Contains("busy")) { }
release.SetResult(); await pending;
try { new BridgeServer().Start(); throw new Exception("TCP must not start"); }
catch (NotSupportedException) { }
try { await PythonFallback.SendAsync("execute_arcpy_code", default); throw new Exception("Python must not run"); }
catch (NotSupportedException) { }
Console.WriteLine("PASS security: authentication, 94 denied tools even with edit grant, arguments, paths/SQL, case, duplicates, local grant/revocation/MCT recheck, concurrency, retired TCP/Python");
if (OperatingSystem.IsWindows())
{
    var privatePath = Path.Combine(Path.GetTempPath(), "mcp-acl-test-" + Guid.NewGuid().ToString("N"));
    try
    {
        BridgeCredentials.WritePrivateText(privatePath, "TEST-ONLY-NOT-A-SECRET");
        var acl = System.IO.FileSystemAclExtensions.GetAccessControl(new FileInfo(privatePath));
        var sid = System.Security.Principal.WindowsIdentity.GetCurrent().User;
        var rules = acl.GetAccessRules(true, true, typeof(System.Security.Principal.SecurityIdentifier));
        if (!acl.AreAccessRulesProtected || rules.Count != 1 || !rules[0].IdentityReference.Equals(sid))
            throw new Exception("Private file ACL is not owner-only");
        BridgeCredentials.WritePrivateText(privatePath, "replacement");
        if (File.ReadAllText(privatePath) != "replacement") throw new Exception("Atomic replacement failed");
    }
    finally { if (File.Exists(privatePath)) File.Delete(privatePath); }
    Console.WriteLine("PASS Windows private-file ACL and atomic replacement; project scope and expired lease denied");
}

namespace ArcGIS.Desktop.Framework.Threading.Tasks
{
    internal static class QueuedTask
    {
        internal static Action BeforeRun;
        public static Task<T> Run<T>(Func<T> action)
        {
            BeforeRun?.Invoke();
            return Task.FromResult(action());
        }
    }
}
