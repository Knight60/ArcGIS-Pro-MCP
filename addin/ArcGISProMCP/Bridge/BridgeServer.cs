using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ArcGISProMCP.Bridge
{
    /// <summary>
    /// The TCP endpoint AI assistants talk to, hosted inside ArcGIS Pro.
    ///
    /// It listens on a background thread and never touches the ArcGIS object
    /// model itself -- CommandRouter marshals that onto the MCT.
    /// </summary>
    internal sealed class BridgeServer : IDisposable
    {
        public const int DefaultPort = 6510;
        private const int PortSearchRange = 10;
        private const int MaxResponseBytes = 4 * 1024 * 1024;

        private TcpListener _listener;
        private CancellationTokenSource _cancellation;

        public bool IsRunning { get; private set; }
        public int Port { get; private set; }
        public int RequestCount { get; private set; }
        public string LastError { get; private set; }
        public DateTime? StartedAt { get; private set; }

        public string Start(int port = DefaultPort, bool autoPort = true)
        {
            if (IsRunning)
                return $"The MCP bridge is already listening on 127.0.0.1:{Port}.";

            Exception lastBindError = null;
            var last = autoPort ? port + PortSearchRange : port;
            for (var candidate = port; candidate <= last; candidate++)
            {
                try
                {
                    var listener = new TcpListener(IPAddress.Loopback, candidate);
                    listener.Start();
                    _listener = listener;
                    Port = candidate;
                    break;
                }
                catch (SocketException exception)
                {
                    lastBindError = exception;
                }
            }

            if (_listener == null)
            {
                throw new InvalidOperationException(
                    $"Could not bind a port in {port}-{last}: {lastBindError?.Message}");
            }

            _cancellation = new CancellationTokenSource();
            IsRunning = true;
            StartedAt = DateTime.Now;
            RequestCount = 0;
            LastError = null;

            _ = Task.Run(() => AcceptLoopAsync(_cancellation.Token));
            WriteInstanceFile();

            return $"MCP bridge listening on 127.0.0.1:{Port} -- {CommandRouter.Count} "
                 + "commands, running in the ArcGIS Pro add-in.";
        }

        public string Stop()
        {
            if (!IsRunning)
                return "The MCP bridge is not running.";

            IsRunning = false;
            try { _cancellation?.Cancel(); } catch { /* shutting down anyway */ }
            try { _listener?.Stop(); } catch { /* ditto */ }
            _listener = null;
            RemoveInstanceFile();
            return "MCP bridge stopped.";
        }

        public void Dispose() => Stop();

        private async Task AcceptLoopAsync(CancellationToken token)
        {
            while (IsRunning && !token.IsCancellationRequested)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false);
                }
                catch (ObjectDisposedException) { return; }
                catch (SocketException) { return; }
                catch (Exception exception)
                {
                    LastError = exception.ToString();
                    return;
                }

                _ = Task.Run(() => ServeClientAsync(client, token));
            }
        }

        private async Task ServeClientAsync(TcpClient client, CancellationToken token)
        {
            try
            {
                using (client)
                using (var stream = client.GetStream())
                {
                    var buffer = new byte[64 * 1024];
                    var pending = new StringBuilder();

                    while (IsRunning && !token.IsCancellationRequested)
                    {
                        var read = await stream.ReadAsync(buffer, 0, buffer.Length, token)
                                               .ConfigureAwait(false);
                        if (read <= 0) return;

                        pending.Append(Encoding.UTF8.GetString(buffer, 0, read));

                        while (true)
                        {
                            var text = pending.ToString();
                            var newline = text.IndexOf('\n');
                            if (newline < 0) break;

                            var line = text.Substring(0, newline);
                            pending.Clear();
                            pending.Append(text.Substring(newline + 1));

                            if (string.IsNullOrWhiteSpace(line)) continue;

                            var response = await HandleAsync(line).ConfigureAwait(false);
                            var payload = Encoding.UTF8.GetBytes(response + "\n");
                            await stream.WriteAsync(payload, 0, payload.Length, token)
                                        .ConfigureAwait(false);
                            await stream.FlushAsync(token).ConfigureAwait(false);
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                LastError = exception.ToString();
            }
        }

        private async Task<string> HandleAsync(string line)
        {
            object id = null;
            try
            {
                using (var document = JsonDocument.Parse(line))
                {
                    var root = document.RootElement;
                    id = root.TryGetProperty("id", out var idElement) && idElement.ValueKind == JsonValueKind.Number
                        ? (object)idElement.GetInt64()
                        : null;

                    var command = root.TryGetProperty("command", out var commandElement)
                        ? commandElement.GetString()
                        : null;

                    var rawParameters = root.TryGetProperty("params", out var parametersElement)
                        ? parametersElement.Clone()
                        : default;

                    RequestCount++;
                    var data = await CommandRouter
                        .DispatchAsync(command, new Params(rawParameters), rawParameters)
                        .ConfigureAwait(false);

                    var response = Protocol.Success(id, data);
                    if (response.Length > MaxResponseBytes)
                    {
                        return Protocol.Failure(id,
                            $"Response too large ({response.Length} bytes). Narrow the request "
                            + "with a where clause, fewer fields, or a smaller limit.");
                    }
                    return response;
                }
            }
            catch (Exception exception)
            {
                LastError = exception.ToString();
                var message = $"{exception.GetType().Name}: {exception.Message}";
                return Protocol.Failure(id, message, exception.StackTrace);
            }
        }

        // --- discovery -------------------------------------------------------
        // Written in the same place and shape as the Python bridge's file, so
        // the MCP server finds whichever one is running without configuration.

        private static string InstanceDirectory =>
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ArcGIS-MCP", "instances");

        private string InstanceFile => Path.Combine(InstanceDirectory, $"bridge-{Port}.json");

        private void WriteInstanceFile()
        {
            try
            {
                Directory.CreateDirectory(InstanceDirectory);
                var payload = new Dictionary<string, object>
                {
                    ["host"] = "127.0.0.1",
                    ["port"] = Port,
                    ["pid"] = System.Diagnostics.Process.GetCurrentProcess().Id,
                    ["project_path"] = ArcGIS.Desktop.Core.Project.Current?.URI,
                    ["command_count"] = CommandRouter.Count,
                    ["implementation"] = "addin",
                };
                File.WriteAllText(InstanceFile,
                    JsonSerializer.Serialize(payload, Protocol.SerializerOptions));
            }
            catch (Exception exception)
            {
                // Discovery is a convenience, never a requirement.
                LastError = exception.Message;
            }
        }

        private void RemoveInstanceFile()
        {
            try
            {
                if (File.Exists(InstanceFile)) File.Delete(InstanceFile);
            }
            catch { /* nothing useful to do */ }
        }
    }
}
