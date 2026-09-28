using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;

namespace ArcGISProMCP.Bridge
{
    /// <summary>Fail-closed policy. No request, environment variable or model can grant editing.</summary>
    internal static class ToolPolicy
    {
        private static readonly HashSet<string> ReadTools = new(StringComparer.Ordinal)
        {
            "ping", "get_capabilities", "get_arcgis_info", "get_project_info", "list_maps",
            "get_layers", "get_layer_info", "get_map_view", "list_bookmarks",
            "get_features", "count_features", "list_fields",
            "get_unique_values", "get_field_statistics", "summarize_features"
        };
        private static readonly HashSet<string> EditTools = new(StringComparer.Ordinal)
        { "rename_layer", "set_layer_visibility", "set_layer_transparency" };
        private static readonly HashSet<string> RemovedArguments = new(StringComparer.Ordinal)
        { "where", "order_by", "include_geometry", "layer_names" };
        private static readonly Lazy<Dictionary<string, JsonElement>> Schemas = new(LoadSchemas);
        private static long _editDeadline;
        private static Func<bool> _editingScope = () => true;
        public static bool EditingEnabled => Environment.TickCount64 < Interlocked.Read(ref _editDeadline) && _editingScope();
        public static void EnableReviewedEditing(Func<bool> scope = null)
        {
            _editingScope = scope ?? (() => true);
            Interlocked.Exchange(ref _editDeadline, Environment.TickCount64 + 15 * 60 * 1000);
        }
        public static void RevokeEditing() => Interlocked.Exchange(ref _editDeadline, 0);
        public static bool IsReadOnly(string name) => ReadTools.Contains(name);
        public static string Classification(string name) => ReadTools.Contains(name) ? "read-only"
            : EditTools.Contains(name) ? "opt-in layer display editing" : "disabled";
        // List the opt-in tools too; a stable catalog avoids stale client caches after revocation.
        public static bool IsAdvertised(string name) => ReadTools.Contains(name) || EditTools.Contains(name);
        public static JsonElement Schema(string name) => Schemas.Value[name];

        public static void Demand(string name, JsonElement arguments)
        {
            if (name == null || !IsAdvertised(name))
                throw new UnauthorizedAccessException("Tool disabled by the hardened security policy.");
            if (EditTools.Contains(name) && !EditingEnabled)
                throw new UnauthorizedAccessException("Read-only mode. A person must enable reviewed layer editing on the MCP ribbon (15-minute lease).");
            if (arguments.ValueKind == JsonValueKind.Undefined)
                arguments = JsonSerializer.SerializeToElement(new { });
            Validate(arguments, Schema(name), "arguments");
            if (arguments.TryGetProperty("layer_name", out var layer)
                && (layer.GetString().IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || string.IsNullOrWhiteSpace(layer.GetString())))
                throw new ArgumentException("Use an existing, uniquely named project layer, not a path or URL.");
            foreach (var key in new[] { "field", "value_field", "fields", "group_by" })
                if (arguments.TryGetProperty(key, out var value))
                    foreach (var field in value.ValueKind == JsonValueKind.Array ? value.EnumerateArray().ToArray() : new[] { value })
                        if (!Regex.IsMatch(field.GetString(), @"\A[A-Za-z_][A-Za-z0-9_.]{0,127}\z"))
                            throw new ArgumentException("Field names must be simple identifiers, not SQL expressions.");
        }

        internal static void CheckJson(JsonElement value, int depth = 0)
        {
            if (depth > 16) throw new ArgumentException("JSON nesting exceeds 16 levels.");
            if (value.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in value.EnumerateObject())
                {
                    if (!names.Add(property.Name)) throw new ArgumentException("Duplicate JSON property.");
                    CheckJson(property.Value, depth + 1);
                }
            }
            if (value.ValueKind == JsonValueKind.Array)
                foreach (var item in value.EnumerateArray()) CheckJson(item, depth + 1);
        }

        private static void Validate(JsonElement value, JsonElement schema, string key)
        {
            CheckJson(value);
            var type = schema.GetProperty("type").GetString();
            bool matches = type switch
            {
                "object" => value.ValueKind == JsonValueKind.Object,
                "array" => value.ValueKind == JsonValueKind.Array,
                "string" => value.ValueKind == JsonValueKind.String && value.GetString().Length is > 0 and <= 512
                    && !value.GetString().Any(char.IsControl),
                "integer" => value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out _),
                "number" => value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var n) && double.IsFinite(n),
                "boolean" => value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False,
                _ => false,
            };
            if (!matches) throw new ArgumentException($"Invalid type or size for {key}.");
            if (type == "object")
            {
                var properties = schema.GetProperty("properties");
                foreach (var property in value.EnumerateObject())
                {
                    if (!properties.TryGetProperty(property.Name, out var child))
                        throw new ArgumentException($"Unsupported argument: {property.Name}.");
                    Validate(property.Value, child, property.Name);
                }
                if (schema.TryGetProperty("required", out var required))
                    foreach (var field in required.EnumerateArray())
                        if (!value.TryGetProperty(field.GetString(), out _))
                            throw new ArgumentException($"Missing argument: {field.GetString()}.");
            }
            if (type == "array")
            {
                if (value.GetArrayLength() is < 1 or > 64) throw new ArgumentException("Array requires 1-64 entries.");
                foreach (var item in value.EnumerateArray()) Validate(item, schema.GetProperty("items"), key);
            }
            if (type == "integer" || type == "number")
            {
                var number = value.GetDouble();
                if (schema.TryGetProperty("minimum", out var min) && number < min.GetDouble()
                    || schema.TryGetProperty("maximum", out var max) && number > max.GetDouble())
                    throw new ArgumentException($"Out of range: {key}.");
            }
        }

        private static Dictionary<string, JsonElement> LoadSchemas()
        {
            using var stream = typeof(ToolPolicy).Assembly.GetManifestResourceStream("ArcGISProMCP.Resources.tools.json")
                ?? throw new InvalidOperationException("Missing tool schemas; refusing dispatch.");
            using var doc = JsonDocument.Parse(stream);
            var result = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            foreach (var tool in doc.RootElement.GetProperty("tools").EnumerateArray())
            {
                var name = tool.GetProperty("name").GetString();
                if (!IsAdvertised(name)) continue;
                var schema = JsonNode.Parse(tool.GetProperty("inputSchema").GetRawText()).AsObject();
                var props = schema["properties"].AsObject();
                schema["additionalProperties"] = false;
                foreach (var key in RemovedArguments) props.Remove(key);
                foreach (var key in new[] { "layer_name", "map_name" })
                    if (props[key] != null) props[key]["description"] = "Existing unique name in the open project; paths and URLs are not accepted.";
                if (props["limit"] != null) { props["limit"]["minimum"] = 1; props["limit"]["maximum"] = 1000; }
                if (props["offset"] != null) { props["offset"]["minimum"] = 0; props["offset"]["maximum"] = 5000; }
                if (props["transparency"] != null) { props["transparency"]["minimum"] = 0; props["transparency"]["maximum"] = 100; }
                if (name == "set_layer_visibility") schema["required"] = new JsonArray("visible", "layer_name");
                result.Add(name, JsonSerializer.SerializeToElement(schema));
            }
            if (result.Count != ReadTools.Count + EditTools.Count) throw new InvalidOperationException("Policy/catalog mismatch.");
            return result;
        }
    }
}
