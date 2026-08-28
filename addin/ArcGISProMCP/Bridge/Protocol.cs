using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;

namespace ArcGISProMCP.Bridge
{
    /// <summary>
    /// The wire format, unchanged from the Python bridge: newline-delimited
    /// JSON over TCP.
    ///
    ///   request : {"id": 1, "command": "get_layers", "params": {...}}
    ///   response: {"id": 1, "success": true, "data": {...}}
    ///   error   : {"id": 1, "success": false, "error": "message"}
    ///
    /// Keeping it identical means the MCP server, its tool catalog and its
    /// tests carry over untouched.
    /// </summary>
    internal static class Protocol
    {
        internal static readonly JsonSerializerOptions SerializerOptions = new JsonSerializerOptions
        {
            // ArcGIS data is full of non-ASCII names; do not escape them.
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = false,
        };

        internal static string Success(object id, object data)
        {
            return JsonSerializer.Serialize(
                new Dictionary<string, object> { ["id"] = id, ["success"] = true, ["data"] = data },
                SerializerOptions);
        }

        internal static string Failure(object id, string error, string detail = null)
        {
            var payload = new Dictionary<string, object>
            {
                ["id"] = id,
                ["success"] = false,
                ["error"] = error,
            };
            if (!string.IsNullOrEmpty(detail))
                payload["traceback"] = detail;
            return JsonSerializer.Serialize(payload, SerializerOptions);
        }
    }

    /// <summary>
    /// Typed, forgiving access to a request's "params" object.
    ///
    /// Every getter tolerates a missing key so command code can read optional
    /// parameters without null dances, and numbers arrive as whatever JSON
    /// type the client happened to send.
    /// </summary>
    public sealed class Params
    {
        private readonly JsonElement _element;
        private readonly bool _hasElement;

        public Params(JsonElement element)
        {
            _element = element;
            _hasElement = element.ValueKind == JsonValueKind.Object;
        }

        public static Params Empty => new Params(default);

        /// <summary>The whole params object, for forwarding a call on unchanged.</summary>
        public JsonElement Root => _element;

        public bool Has(string name)
        {
            return _hasElement
                   && _element.TryGetProperty(name, out var value)
                   && value.ValueKind != JsonValueKind.Null;
        }

        public JsonElement Raw(string name)
        {
            if (_hasElement && _element.TryGetProperty(name, out var value))
                return value;
            return default;
        }

        public string GetString(string name, string fallback = null)
        {
            if (!Has(name)) return fallback;
            var value = _element.GetProperty(name);
            return value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : value.ToString();
        }

        public string Require(string name)
        {
            var value = GetString(name);
            if (string.IsNullOrWhiteSpace(value))
                throw new ArgumentException($"Missing required parameter: {name}");
            return value;
        }

        public bool GetBool(string name, bool fallback = false)
        {
            if (!Has(name)) return fallback;
            var value = _element.GetProperty(name);
            switch (value.ValueKind)
            {
                case JsonValueKind.True: return true;
                case JsonValueKind.False: return false;
                case JsonValueKind.Number: return value.GetDouble() != 0;
                case JsonValueKind.String:
                    return bool.TryParse(value.GetString(), out var parsed) ? parsed : fallback;
                default: return fallback;
            }
        }

        public int GetInt(string name, int fallback = 0)
        {
            return (int)Math.Round(GetDouble(name, fallback));
        }

        public double GetDouble(string name, double fallback = 0)
        {
            if (!Has(name)) return fallback;
            var value = _element.GetProperty(name);
            if (value.ValueKind == JsonValueKind.Number) return value.GetDouble();
            if (value.ValueKind == JsonValueKind.String
                && double.TryParse(value.GetString(), NumberStyles.Any,
                                   CultureInfo.InvariantCulture, out var parsed))
                return parsed;
            return fallback;
        }

        public double? GetOptionalDouble(string name)
        {
            return Has(name) ? GetDouble(name) : (double?)null;
        }

        public List<string> GetStringList(string name)
        {
            if (!Has(name)) return null;
            var value = _element.GetProperty(name);
            if (value.ValueKind == JsonValueKind.String)
                return new List<string> { value.GetString() };
            if (value.ValueKind != JsonValueKind.Array) return null;
            return value.EnumerateArray()
                        .Select(item => item.ValueKind == JsonValueKind.String
                                        ? item.GetString() : item.ToString())
                        .ToList();
        }

        public List<int> GetIntList(string name)
        {
            if (!Has(name)) return null;
            var value = _element.GetProperty(name);
            if (value.ValueKind != JsonValueKind.Array) return null;
            return value.EnumerateArray()
                        .Where(item => item.ValueKind == JsonValueKind.Number)
                        .Select(item => item.GetInt32())
                        .ToList();
        }

        /// <summary>An [r, g, b] or [r, g, b, a] colour, 0-255 with 0-100 alpha.</summary>
        public int[] GetColor(string name)
        {
            var value = Raw(name);
            if (value.ValueKind != JsonValueKind.Array) return null;
            var parts = value.EnumerateArray()
                             .Where(item => item.ValueKind == JsonValueKind.Number)
                             .Select(item => item.GetInt32())
                             .ToArray();
            if (parts.Length < 3) return null;
            return parts.Length >= 4
                ? new[] { parts[0], parts[1], parts[2], parts[3] }
                : new[] { parts[0], parts[1], parts[2], 100 };
        }

        public IEnumerable<Params> GetObjectList(string name)
        {
            var value = Raw(name);
            if (value.ValueKind != JsonValueKind.Array) yield break;
            foreach (var item in value.EnumerateArray())
                yield return new Params(item);
        }

        public Dictionary<string, JsonElement> GetObject(string name)
        {
            var value = Raw(name);
            if (value.ValueKind != JsonValueKind.Object) return null;
            return value.EnumerateObject().ToDictionary(p => p.Name, p => p.Value);
        }
    }
}
