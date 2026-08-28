using System;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ArcGISProMCP.Bridge
{
    /// <summary>
    /// Forwards commands this add-in does not implement to the Python bridge.
    ///
    /// That bridge still owns arcpy -- execute_arcpy_code above all, the one
    /// tool that can do anything the typed commands do not cover. It listens
    /// on its own port so the two can run side by side, and it is optional:
    /// when it is not there the caller gets a clear message rather than a
    /// hang.
    /// </summary>
    internal static class PythonFallback
    {
        public const int DefaultPort = 6511;

        private static readonly SemaphoreSlim Gate = new SemaphoreSlim(1, 1);
        private static int _port = DefaultPort;
        private static int _forwarded;
        private static string _lastError;

        public static int Port
        {
            get => _port;
            set => _port = value;
        }

        public static object Describe()
        {
            return new Dictionary<string, object>
            {
                ["target"] = "Python bridge (arcpy)",
                ["host"] = "127.0.0.1",
                ["port"] = _port,
                ["forwarded_commands"] = _forwarded,
                ["last_error"] = _lastError,
                ["note"] = "Unknown commands are forwarded here, which is where "
                         + "execute_arcpy_code and any not-yet-ported command lives.",
            };
        }

        public static async Task<object> SendAsync(string command, JsonElement parameters)
        {
            var request = new Dictionary<string, object>
            {
                ["id"] = 1,
                ["command"] = command,
                ["params"] = parameters.ValueKind == JsonValueKind.Undefined
                    ? new Dictionary<string, object>()
                    : (object)parameters,
            };
            var line = JsonSerializer.Serialize(request, Protocol.SerializerOptions) + "\n";

            // One request at a time: the Python bridge is single-threaded for
            // arcpy anyway, and this keeps the socket handling simple.
            await Gate.WaitAsync().ConfigureAwait(false);
            try
            {
                using (var client = new TcpClient())
                {
                    var connect = client.ConnectAsync("127.0.0.1", _port);
                    if (await Task.WhenAny(connect, Task.Delay(2000)).ConfigureAwait(false) != connect
                        || !client.Connected)
                    {
                        throw new InvalidOperationException(
                            $"'{command}' is not implemented by the ArcGIS Pro add-in, and the "
                            + $"Python bridge is not listening on 127.0.0.1:{_port}. Start it from "
                            + "the ArcGIS Pro Python window with:  import mcp_bridge; "
                            + "mcp_bridge.start_server(port=" + _port + "); mcp_bridge.start_pump()");
                    }
                    await connect.ConfigureAwait(false);

                    using (var stream = client.GetStream())
                    {
                        var payload = Encoding.UTF8.GetBytes(line);
                        await stream.WriteAsync(payload, 0, payload.Length).ConfigureAwait(false);
                        await stream.FlushAsync().ConfigureAwait(false);

                        var response = await ReadLineAsync(stream).ConfigureAwait(false);
                        _forwarded++;
                        return Unwrap(command, response);
                    }
                }
            }
            catch (Exception exception)
            {
                _lastError = exception.Message;
                throw;
            }
            finally
            {
                Gate.Release();
            }
        }

        private static async Task<string> ReadLineAsync(NetworkStream stream)
        {
            var buffer = new byte[64 * 1024];
            var builder = new StringBuilder();
            while (true)
            {
                var read = await stream.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false);
                if (read <= 0)
                    throw new InvalidOperationException("The Python bridge closed the connection.");
                builder.Append(Encoding.UTF8.GetString(buffer, 0, read));
                var text = builder.ToString();
                var newline = text.IndexOf('\n');
                if (newline >= 0)
                    return text.Substring(0, newline);
            }
        }

        /// <summary>
        /// The Python bridge answers in the same envelope we do, so unwrap it
        /// rather than nesting one response inside another.
        /// </summary>
        private static object Unwrap(string command, string response)
        {
            using (var document = JsonDocument.Parse(response))
            {
                var root = document.RootElement;
                var succeeded = root.TryGetProperty("success", out var success)
                                && success.ValueKind == JsonValueKind.True;
                if (!succeeded)
                {
                    var message = root.TryGetProperty("error", out var error)
                        ? error.GetString()
                        : "unknown error";
                    throw new InvalidOperationException(
                        $"Python bridge error in {command}: {message}");
                }
                return root.TryGetProperty("data", out var data)
                    ? JsonSerializer.Deserialize<object>(data.GetRawText(), Protocol.SerializerOptions)
                    : null;
            }
        }
    }
}
