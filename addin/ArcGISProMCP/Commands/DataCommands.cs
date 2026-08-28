using System;
using System.Collections.Generic;
using System.Linq;
using ArcGIS.Core.Data;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Reading attributes, summarising them, and selecting features.</summary>
    internal static class DataCommands
    {
        private const string Group = "data";
        private const int MaxRows = 5000;

        public static void Register()
        {
            CommandRouter.Register("get_features", Group,
                "Read attribute rows, with an optional where clause and field subset.",
                GetFeatures);

            CommandRouter.Register("count_features", Group,
                "Count features, optionally matching a where clause.", CountFeatures);

            CommandRouter.Register("get_unique_values", Group,
                "Distinct values of a field, with counts.", GetUniqueValues);

            CommandRouter.Register("get_field_statistics", Group,
                "min / max / mean / median / sum / standard deviation of a numeric field.",
                GetFieldStatistics);

            CommandRouter.Register("summarize_features", Group,
                "Group rows by one or more fields and aggregate.", Summarize);

            CommandRouter.Register("select_features", "selection",
                "Select features by SQL where clause.", SelectFeatures);

            CommandRouter.Register("clear_selection", "selection",
                "Clear the selection on one layer, or on the whole map.", ClearSelection);

            CommandRouter.Register("get_selection", "selection",
                "Report what is currently selected.", GetSelection);
        }

        // --- shared plumbing -------------------------------------------------

        /// <summary>
        /// What to read from: a layer, a standalone table, or a dataset path.
        /// The caller disposes it.
        /// </summary>
        private static DataSource Source(Params parameters) => DataSource.Resolve(parameters);

        private static QueryFilter BuildFilter(Params parameters, IEnumerable<string> subFields = null)
        {
            var filter = new QueryFilter();
            var where = parameters.GetString("where");
            if (!string.IsNullOrWhiteSpace(where)) filter.WhereClause = where;

            var fields = subFields?.ToList();
            if (fields != null && fields.Count > 0)
                filter.SubFields = string.Join(",", fields);

            // order_by is applied after reading, not here: shapefiles and
            // several other sources silently ignore PostfixClause.

            return filter;
        }

        private sealed class OrderTerm
        {
            public string Field;
            public bool Descending;
        }

        /// <summary>Parse "AreaKm2 DESC, NAME" into terms to sort by.</summary>
        private static List<OrderTerm> ParseOrderBy(string clause)
        {
            if (string.IsNullOrWhiteSpace(clause)) return null;
            var terms = new List<OrderTerm>();
            foreach (var part in clause.Split(','))
            {
                var words = part.Trim().Split(new[] { ' ' },
                                              StringSplitOptions.RemoveEmptyEntries);
                if (words.Length == 0) continue;
                terms.Add(new OrderTerm
                {
                    Field = words[0],
                    Descending = words.Length > 1
                                 && words[1].Equals("DESC", StringComparison.OrdinalIgnoreCase),
                });
            }
            return terms.Count > 0 ? terms : null;
        }

        private static void Sort(List<Dictionary<string, object>> rows, List<OrderTerm> terms)
        {
            rows.Sort((left, right) =>
            {
                foreach (var term in terms)
                {
                    left.TryGetValue(term.Field, out var a);
                    right.TryGetValue(term.Field, out var b);
                    var comparison = Compare(a, b);
                    if (comparison != 0) return term.Descending ? -comparison : comparison;
                }
                return 0;
            });
        }

        private static int Compare(object left, object right)
        {
            if (left == null && right == null) return 0;
            if (left == null) return -1;
            if (right == null) return 1;
            if (left is IComparable comparable && left.GetType() == right.GetType())
                return comparable.CompareTo(right);
            return string.Compare(left.ToString(), right.ToString(), StringComparison.Ordinal);
        }

        /// <summary>Field names worth returning: everything but geometry and blobs.</summary>
        private static List<string> ReadableFields(DataSource source)
        {
            return source.Definition.GetFields()
                .Where(f => f.FieldType != FieldType.Geometry
                            && f.FieldType != FieldType.Blob
                            && f.FieldType != FieldType.Raster)
                .Select(f => f.Name)
                .ToList();
        }

        // --- reading ---------------------------------------------------------

        private static object GetFeatures(Params parameters)
        {
            using var source = Source(parameters);
            var limit = Math.Min(parameters.GetInt("limit", 50), MaxRows);
            var offset = Math.Max(parameters.GetInt("offset"), 0);
            var includeGeometry = parameters.GetBool("include_geometry");

            var fields = parameters.GetStringList("fields") ?? ReadableFields(source);
            var filter = BuildFilter(parameters, includeGeometry ? null : fields);

            var orderBy = ParseOrderBy(parameters.GetString("order_by"));
            // Sorting means reading the matches before paging them, so a
            // sorted request reads up to the row cap instead of stopping at
            // offset + limit.
            var readCap = orderBy == null ? offset + limit : MaxRows;

            var rows = new List<Dictionary<string, object>>();
            var truncated = false;

            using (var cursor = source.Search(filter))
            {
                while (cursor.MoveNext())
                {
                    if (rows.Count >= readCap)
                    {
                        truncated = true;
                        break;
                    }
                    using (var row = cursor.Current)
                    {
                        var record = new Dictionary<string, object>();
                        foreach (var field in fields)
                        {
                            try { record[field] = MapHelpers.Normalise(row[field]); }
                            catch { record[field] = null; }
                        }
                        if (includeGeometry && row is Feature feature)
                            record["SHAPE@WKT"] = MapHelpers.ToWkt(feature.GetShape());
                        rows.Add(record);
                    }
                }
            }

            if (orderBy != null) Sort(rows, orderBy);
            var page = rows.Skip(offset).Take(limit).ToList();

            var result = new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["fields"] = fields,
                ["count"] = page.Count,
                ["offset"] = offset,
                ["limit"] = limit,
                ["features"] = page,
            };
            if (orderBy != null)
            {
                result["ordered_by"] = orderBy.Select(o => o.Field + (o.Descending ? " DESC" : ""))
                                              .ToList();
                if (truncated)
                    result["order_warning"] =
                        $"Only the first {MaxRows} matching rows were read before sorting, "
                        + "so this is not the true top of the whole layer. Narrow it with a "
                        + "where clause.";
            }
            return result;
        }

        private static object CountFeatures(Params parameters)
        {
            using var source = Source(parameters);
            var where = parameters.GetString("where");

            // Always count through the source's own Search: a table's GetCount
            // reports every row and ignores the layer's definition query,
            // which is not what anyone asking a layer for its count means.
            long count = 0;
            using (var cursor = source.Search(BuildFilter(parameters)))
            {
                while (cursor.MoveNext())
                {
                    using (cursor.Current) count++;
                }
            }

            return new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["where"] = where,
                ["count"] = count,
            };
        }

        private static object GetUniqueValues(Params parameters)
        {
            using var source = Source(parameters);
            var field = parameters.Require("field");
            var limit = Math.Min(parameters.GetInt("limit", 200), MaxRows);

            var counts = new Dictionary<string, long>();
            var values = new Dictionary<string, object>();

            using (var cursor = source.Search(BuildFilter(parameters, new[] { field })))
            {
                while (cursor.MoveNext())
                {
                    using (var row = cursor.Current)
                    {
                        var value = MapHelpers.Normalise(row[field]);
                        var key = value?.ToString() ?? " null";
                        counts.TryGetValue(key, out var current);
                        counts[key] = current + 1;
                        values[key] = value;
                    }
                }
            }

            var ordered = counts.OrderBy(pair => pair.Key, StringComparer.Ordinal)
                                .Take(limit)
                                .Select(pair => new Dictionary<string, object>
                                {
                                    ["value"] = values[pair.Key],
                                    ["count"] = pair.Value,
                                })
                                .ToList();

            return new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["field"] = field,
                ["distinct_count"] = counts.Count,
                ["values"] = ordered,
                ["truncated"] = counts.Count > limit,
            };
        }

        private static object GetFieldStatistics(Params parameters)
        {
            using var source = Source(parameters);
            var field = parameters.Require("field");

            var numbers = new List<double>();
            long nulls = 0, total = 0;

            using (var cursor = source.Search(BuildFilter(parameters, new[] { field })))
            {
                while (cursor.MoveNext())
                {
                    using (var row = cursor.Current)
                    {
                        total++;
                        var value = row[field];
                        if (value == null) { nulls++; continue; }
                        if (double.TryParse(value.ToString(),
                                            System.Globalization.NumberStyles.Any,
                                            System.Globalization.CultureInfo.InvariantCulture,
                                            out var number))
                            numbers.Add(number);
                    }
                }
            }

            var statistics = new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["field"] = field,
                ["count"] = total,
                ["null_count"] = nulls,
            };

            if (numbers.Count > 0)
            {
                numbers.Sort();
                var mean = numbers.Average();
                var variance = numbers.Sum(v => (v - mean) * (v - mean)) / numbers.Count;
                statistics["min"] = numbers.First();
                statistics["max"] = numbers.Last();
                statistics["sum"] = numbers.Sum();
                statistics["mean"] = mean;
                statistics["median"] = numbers.Count % 2 == 1
                    ? numbers[numbers.Count / 2]
                    : (numbers[numbers.Count / 2 - 1] + numbers[numbers.Count / 2]) / 2;
                statistics["std_dev"] = Math.Sqrt(variance);
            }

            return statistics;
        }

        private static object Summarize(Params parameters)
        {
            using var source = Source(parameters);
            var groupBy = parameters.GetStringList("group_by");
            if (groupBy == null || groupBy.Count == 0)
                throw new ArgumentException("group_by is required.");
            var valueField = parameters.GetString("value_field");
            var limit = Math.Min(parameters.GetInt("limit", 200), MaxRows);

            var subFields = new List<string>(groupBy);
            if (!string.IsNullOrWhiteSpace(valueField)) subFields.Add(valueField);

            var buckets = new Dictionary<string, (List<object> Key, long Count, List<double> Values)>();

            using (var cursor = source.Search(BuildFilter(parameters, subFields)))
            {
                while (cursor.MoveNext())
                {
                    using (var row = cursor.Current)
                    {
                        var key = groupBy.Select(f => MapHelpers.Normalise(row[f])).ToList();
                        var id = string.Join("", key.Select(k => k?.ToString() ?? ""));

                        if (!buckets.TryGetValue(id, out var bucket))
                            bucket = (key, 0, new List<double>());

                        var values = bucket.Values;
                        if (!string.IsNullOrWhiteSpace(valueField))
                        {
                            var raw = row[valueField];
                            if (raw != null && double.TryParse(
                                    raw.ToString(),
                                    System.Globalization.NumberStyles.Any,
                                    System.Globalization.CultureInfo.InvariantCulture,
                                    out var number))
                                values.Add(number);
                        }
                        buckets[id] = (bucket.Key, bucket.Count + 1, values);
                    }
                }
            }

            var groups = buckets.Values.Select(bucket =>
            {
                var entry = new Dictionary<string, object>();
                for (var i = 0; i < groupBy.Count; i++) entry[groupBy[i]] = bucket.Key[i];
                entry["count"] = bucket.Count;
                if (bucket.Values.Count > 0)
                {
                    entry["sum"] = bucket.Values.Sum();
                    entry["mean"] = bucket.Values.Average();
                    entry["min"] = bucket.Values.Min();
                    entry["max"] = bucket.Values.Max();
                }
                return entry;
            })
            .OrderByDescending(entry => entry.TryGetValue("sum", out var sum)
                                        ? Convert.ToDouble(sum)
                                        : Convert.ToDouble(entry["count"]))
            .ToList();

            return new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["group_by"] = groupBy,
                ["value_field"] = valueField,
                ["group_count"] = groups.Count,
                ["groups"] = groups.Take(limit).ToList(),
                ["truncated"] = groups.Count > limit,
            };
        }

        // --- selection -------------------------------------------------------

        private static SelectionCombinationMethod ParseMethod(string method)
        {
            switch ((method ?? "NEW_SELECTION").ToUpperInvariant())
            {
                case "ADD_TO_SELECTION": return SelectionCombinationMethod.Add;
                case "REMOVE_FROM_SELECTION": return SelectionCombinationMethod.Subtract;
                case "SUBSET_SELECTION": return SelectionCombinationMethod.And;
                case "SWITCH_SELECTION": return SelectionCombinationMethod.XOR;
                default: return SelectionCombinationMethod.New;
            }
        }

        /// <summary>A selection lives on a map layer, so these need one.</summary>
        private static BasicFeatureLayer SelectableLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            return MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"));
        }

        private static object SelectFeatures(Params parameters)
        {
            var layer = SelectableLayer(parameters);
            var method = parameters.GetString("method", "NEW_SELECTION");
            var filter = new QueryFilter { WhereClause = parameters.Require("where") };

            var selection = layer.Select(filter, ParseMethod(method));

            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["method"] = method,
                ["where"] = filter.WhereClause,
                ["selected_count"] = selection?.GetCount() ?? 0,
            };
        }

        private static object ClearSelection(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.GetString("layer_name");

            if (string.IsNullOrWhiteSpace(name))
            {
                map.ClearSelection();
                return new Dictionary<string, object>
                {
                    ["cleared"] = $"all layers in map '{map.Name}'",
                };
            }

            var layer = MapHelpers.RequireFeatureLayer(map, name);
            layer.ClearSelection();
            return new Dictionary<string, object> { ["cleared"] = layer.Name };
        }

        private static object GetSelection(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.GetString("layer_name");
            var limit = parameters.GetInt("limit", 100);

            var layers = string.IsNullOrWhiteSpace(name)
                ? map.GetLayersAsFlattenedList().OfType<BasicFeatureLayer>().ToList()
                : new List<BasicFeatureLayer> { MapHelpers.RequireFeatureLayer(map, name) };

            var selections = new List<Dictionary<string, object>>();
            long total = 0;

            foreach (var layer in layers)
            {
                var selection = layer.GetSelection();
                var oids = selection?.GetObjectIDs();
                if (oids == null || oids.Count == 0) continue;

                total += oids.Count;
                selections.Add(new Dictionary<string, object>
                {
                    ["layer"] = layer.Name,
                    ["selected_count"] = oids.Count,
                    ["oids"] = oids.Take(limit).ToList(),
                    ["truncated"] = oids.Count > limit,
                });
            }

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["selections"] = selections,
                ["total_selected"] = total,
            };
        }
    }
}
