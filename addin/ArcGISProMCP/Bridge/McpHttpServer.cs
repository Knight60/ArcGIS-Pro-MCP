using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ArcGISProMCP.Bridge
{
    /// <summary>
    /// Speaks MCP directly, over HTTP, from inside ArcGIS Pro.
    ///
    /// The stdio transport cannot work here: the client starts an MCP server
    /// as a child process, and this one is already running inside Pro. HTTP
    /// inverts that -- the client connects to a URL -- so the whole setup
    /// becomes installing the add-in and pointing a client at it:
    ///
    ///     claude mcp add --transport http arcgis http://127.0.0.1:6520/mcp
    ///
    /// Tool schemas come from the same catalog.py the Python server uses,
    /// exported by scripts/export_tool_schemas.py, so there is still only one
    /// place tools are defined.
    ///
    /// Bound to the loopback address only: this exposes the user's open
    /// project, and nothing outside the machine should reach it.
    /// </summary>
    internal sealed class McpHttpServer : IDisposable
    {
        public const int DefaultPort = 6520;
        private const string ToolResource = "ArcGISProMCP.Resources.tools.json";
        private const string ServerName = "ArcGIS Pro MCP";
        private const string FallbackProtocol = "2024-11-05";

        private HttpListener _listener;
        private CancellationTokenSource _cancellation;
        private readonly Lazy<List<ToolDefinition>> _tools =
            new Lazy<List<ToolDefinition>>(LoadTools);

        public bool IsRunning { get; private set; }
        public int Port { get; private set; }
        public int RequestCount { get; private set; }
        public string LastError { get; private set; }

        private sealed class ToolDefinition
        {
            public string Name;
            public string Description;
            public JsonElement InputSchema;
            public bool ReturnsImage;
        }

        // --- lifecycle --------------------------------------------------------

        public string Start(int port = DefaultPort)
        {
            if (IsRunning) return $"MCP over HTTP is already on port {Port}.";

            var listener = new HttpListener();
            listener.Prefixes.Add($"http://127.0.0.1:{port}/mcp/");
            try
            {
                listener.Start();
            }
            catch (HttpListenerException exception)
            {
                throw new InvalidOperationException(
                    $"Could not listen on http://127.0.0.1:{port}/mcp/ ({exception.Message}). "
                    + "Another process may hold the port.", exception);
            }

            _listener = listener;
            Port = port;
            IsRunning = true;
            RequestCount = 0;
            _cancellation = new CancellationTokenSource();
            _ = Task.Run(() => AcceptLoopAsync(_cancellation.Token));

            return $"MCP over HTTP on http://127.0.0.1:{port}/mcp -- "
                 + $"{_tools.Value.Count} tools.";
        }

        public string Stop()
        {
            if (!IsRunning) return "MCP over HTTP is not running.";
            IsRunning = false;
            try { _cancellation?.Cancel(); } catch { }
            try { _listener?.Stop(); } catch { }
            _listener = null;
            return "MCP over HTTP stopped.";
        }

        public void Dispose() => Stop();

        private async Task AcceptLoopAsync(CancellationToken token)
        {
            while (IsRunning && !token.IsCancellationRequested)
            {
                HttpListenerContext context;
                try
                {
                    context = await _listener.GetContextAsync().ConfigureAwait(false);
                }
                catch (ObjectDisposedException) { return; }
                catch (HttpListenerException) { return; }
                catch (Exception exception)
                {
                    LastError = exception.ToString();
                    return;
                }
                _ = Task.Run(() => ServeAsync(context));
            }
        }

        // --- HTTP -------------------------------------------------------------

        private async Task ServeAsync(HttpListenerContext context)
        {
            try
            {
                if (context.Request.HttpMethod == "POST")
                {
                    string body;
                    using (var reader = new StreamReader(
                               context.Request.InputStream, Encoding.UTF8))
                        body = await reader.ReadToEndAsync().ConfigureAwait(false);

                    RequestCount++;
                    var response = await HandleAsync(body).ConfigureAwait(false);

                    if (response == null)
                    {
                        // A notification: acknowledged, nothing to return.
                        context.Response.StatusCode = 202;
                        context.Response.Close();
                        return;
                    }
                    await WriteAsync(context, 200, response).ConfigureAwait(false);
                    return;
                }

                // Server-initiated streaming is not offered; everything this
                // server does is a reply to a request.
                context.Response.StatusCode = 405;
                context.Response.Close();
            }
            catch (Exception exception)
            {
                LastError = exception.ToString();
                try { context.Response.Abort(); } catch { }
            }
        }

        private static async Task WriteAsync(HttpListenerContext context, int status,
                                             string json)
        {
            var payload = Encoding.UTF8.GetBytes(json);
            context.Response.StatusCode = status;
            context.Response.ContentType = "application/json";
            context.Response.ContentLength64 = payload.Length;
            await context.Response.OutputStream.WriteAsync(payload, 0, payload.Length)
                .ConfigureAwait(false);
            context.Response.Close();
        }

        // --- JSON-RPC ---------------------------------------------------------

        private async Task<string> HandleAsync(string body)
        {
            JsonElement request;
            try
            {
                request = JsonDocument.Parse(body).RootElement;
            }
            catch (Exception exception)
            {
                return Error(null, -32700, $"Parse error: {exception.Message}");
            }

            var method = request.TryGetProperty("method", out var m) ? m.GetString() : null;
            var hasId = request.TryGetProperty("id", out var id)
                        && id.ValueKind != JsonValueKind.Null;
            object requestId = !hasId ? null
                : id.ValueKind == JsonValueKind.Number ? (object)id.GetInt64() : id.GetString();

            // Notifications get no reply at all.
            if (!hasId) return null;

            try
            {
                switch (method)
                {
                    case "initialize":
                        return Result(requestId, Initialize(request));
                    case "ping":
                        return Result(requestId, new Dictionary<string, object>());
                    case "tools/list":
                        return Result(requestId, new Dictionary<string, object>
                        {
                            ["tools"] = _tools.Value.Select(tool =>
                                new Dictionary<string, object>
                                {
                                    ["name"] = tool.Name,
                                    ["description"] = tool.Description,
                                    ["inputSchema"] = tool.InputSchema,
                                }).ToList(),
                        });
                    case "tools/call":
                        return Result(requestId,
                            await CallToolAsync(request).ConfigureAwait(false));
                    default:
                        return Error(requestId, -32601, $"Unknown method: {method}");
                }
            }
            catch (Exception exception)
            {
                LastError = exception.ToString();
                return Error(requestId, -32603,
                    $"{exception.GetType().Name}: {exception.Message}");
            }
        }

        private object Initialize(JsonElement request)
        {
            var requested = FallbackProtocol;
            if (request.TryGetProperty("params", out var parameters)
                && parameters.TryGetProperty("protocolVersion", out var version)
                && version.ValueKind == JsonValueKind.String)
            {
                requested = version.GetString();
            }

            return new Dictionary<string, object>
            {
                // Echo the client's version: this server has no features that
                // differ between the revisions it would otherwise have to pick.
                ["protocolVersion"] = requested,
                ["capabilities"] = new Dictionary<string, object>
                {
                    ["tools"] = new Dictionary<string, object>(),
                },
                ["serverInfo"] = new Dictionary<string, object>
                {
                    ["name"] = ServerName,
                    ["version"] = typeof(McpHttpServer).Assembly.GetName().Version?.ToString(),
                },
                ["instructions"] =
                    "Control the ArcGIS Pro session this add-in is running inside. "
                    + "Start with get_project_info or get_layers. map_name defaults to "
                    + "the active map. Anything not covered by a tool can be run with "
                    + "run_geoprocessing_tool; check a tool's parameters first with "
                    + "describe_geoprocessing_tool.",
            };
        }

        private async Task<object> CallToolAsync(JsonElement request)
        {
            if (!request.TryGetProperty("params", out var parameters))
                throw new ArgumentException("tools/call needs params.");

            var name = parameters.TryGetProperty("name", out var n) ? n.GetString() : null;
            var arguments = parameters.TryGetProperty("arguments", out var a)
                ? a.Clone() : default;

            var tool = _tools.Value.FirstOrDefault(
                t => string.Equals(t.Name, name, StringComparison.OrdinalIgnoreCase));

            try
            {
                var data = await CommandRouter
                    .DispatchAsync(name, new Params(arguments), arguments)
                    .ConfigureAwait(false);
                return ToolResult(data, tool?.ReturnsImage ?? false);
            }
            catch (Exception exception)
            {
                // A tool that fails is a result the model should see and can
                // act on, not a transport-level error.
                return new Dictionary<string, object>
                {
                    ["isError"] = true,
                    ["content"] = new List<object>
                    {
                        new Dictionary<string, object>
                        {
                            ["type"] = "text",
                            ["text"] = $"{exception.GetType().Name}: {exception.Message}",
                        },
                    },
                };
            }
        }

        /// <summary>Turn a command's result into MCP content blocks.</summary>
        private static object ToolResult(object data, bool mayHaveImage)
        {
            var content = new List<object>();
            string image = null, imageFormat = "png";

            if (mayHaveImage && data is IDictionary<string, object> dictionary)
            {
                // The image travels beside the summary; split it back out so
                // the client renders it rather than showing base64 text.
                if (dictionary.TryGetValue("image_base64", out var encoded))
                {
                    image = encoded as string;
                    dictionary.Remove("image_base64");
                }
                if (dictionary.TryGetValue("image_format", out var format))
                {
                    imageFormat = format as string ?? "png";
                    dictionary.Remove("image_format");
                }
            }

            content.Add(new Dictionary<string, object>
            {
                ["type"] = "text",
                ["text"] = JsonSerializer.Serialize(data, Protocol.SerializerOptions),
            });

            if (!string.IsNullOrEmpty(image))
            {
                content.Add(new Dictionary<string, object>
                {
                    ["type"] = "image",
                    ["data"] = image,
                    ["mimeType"] = imageFormat == "jpeg" ? "image/jpeg" : "image/png",
                });
            }

            return new Dictionary<string, object> { ["content"] = content };
        }

        private static string Result(object id, object result)
        {
            return JsonSerializer.Serialize(new Dictionary<string, object>
            {
                ["jsonrpc"] = "2.0",
                ["id"] = id,
                ["result"] = result,
            }, Protocol.SerializerOptions);
        }

        private static string Error(object id, int code, string message)
        {
            return JsonSerializer.Serialize(new Dictionary<string, object>
            {
                ["jsonrpc"] = "2.0",
                ["id"] = id,
                ["error"] = new Dictionary<string, object>
                {
                    ["code"] = code,
                    ["message"] = message,
                },
            }, Protocol.SerializerOptions);
        }

        // --- tool schemas -----------------------------------------------------

        private static List<ToolDefinition> LoadTools()
        {
            var tools = new List<ToolDefinition>();
            try
            {
                var assembly = typeof(McpHttpServer).Assembly;
                using (var stream = assembly.GetManifestResourceStream(ToolResource))
                {
                    if (stream == null) return tools;
                    using (var reader = new StreamReader(stream))
                    {
                        var document = JsonDocument.Parse(reader.ReadToEnd());
                        foreach (var entry in document.RootElement
                                     .GetProperty("tools").EnumerateArray())
                        {
                            tools.Add(new ToolDefinition
                            {
                                Name = entry.GetProperty("name").GetString(),
                                Description = entry.GetProperty("description").GetString(),
                                InputSchema = entry.GetProperty("inputSchema").Clone(),
                                ReturnsImage = entry.TryGetProperty("returnsImage", out var i)
                                               && i.ValueKind == JsonValueKind.True,
                            });
                        }
                    }
                }
            }
            catch
            {
                // With no schemas the server still answers, with no tools --
                // clearer than refusing to start.
            }
            return tools;
        }
    }
}
