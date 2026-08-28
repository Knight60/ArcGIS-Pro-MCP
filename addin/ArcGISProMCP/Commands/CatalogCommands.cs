using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ArcGIS.Core.Data;
using ArcGIS.Core.Data.Raster;
using ArcGIS.Desktop.Catalog;
using ArcGIS.Desktop.Core;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Finding data before it is on a map. Everything here works on paths, so
    /// none of it needs a layer to exist first.
    /// </summary>
    internal static class CatalogCommands
    {
        private const string Group = "catalog";
        private const int MaxItems = 500;

        private static readonly string[] DataExtensions =
        {
            ".shp", ".gdb", ".tif", ".tiff", ".img", ".lyrx", ".gpkg", ".csv",
            ".xlsx", ".kml", ".kmz", ".geojson", ".json", ".dwg", ".sde",
            ".aprx", ".mdb", ".nc", ".las", ".zip",
        };

        public static void Register()
        {
            CommandRouter.Register("list_workspace_contents", Group,
                "List the datasets inside a geodatabase or folder.", ListWorkspace);
            CommandRouter.Register("describe_dataset", Group,
                "Describe any dataset by path without adding it to a map.", Describe);
            CommandRouter.Register("search_data", Group,
                "Find datasets by name across the project's workspaces.", Search);
            CommandRouter.Register("list_folder", Group,
                "List GIS files and subfolders on disk.", ListFolder);
            CommandRouter.Register("get_project_items", Group,
                "Folder connections, databases and toolboxes in the project.",
                GetProjectItems);
            CommandRouter.Register("add_folder_connection", Group,
                "Register a folder with the project.", AddFolderConnection);
        }

        // --- opening workspaces ----------------------------------------------

        private static string ResolvePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            return Path.IsPathRooted(path)
                ? path
                : Path.Combine(Project.Current?.HomeFolderPath ?? string.Empty, path);
        }

        /// <summary>Open a .gdb or a folder of shapefiles as a datastore.</summary>
        private static Datastore OpenWorkspace(string path)
        {
            if (!Directory.Exists(path) && !File.Exists(path))
                throw new ArgumentException($"Workspace does not exist: {path}");

            if (path.EndsWith(".gdb", StringComparison.OrdinalIgnoreCase))
                return new Geodatabase(new FileGeodatabaseConnectionPath(new Uri(path)));
            if (path.EndsWith(".sde", StringComparison.OrdinalIgnoreCase))
                return new Geodatabase(new DatabaseConnectionFile(new Uri(path)));

            return new FileSystemDatastore(new FileSystemConnectionPath(
                new Uri(path), FileSystemDatastoreType.Shapefile));
        }

        private static object ListWorkspace(Params parameters)
        {
            var path = ResolvePath(parameters.GetString("workspace"))
                       ?? Project.Current?.DefaultGeodatabasePath
                       ?? throw new InvalidOperationException("No workspace and no project.");
            var wildcard = parameters.GetString("wildcard");
            var limit = parameters.GetInt("limit", MaxItems);
            var withDetails = parameters.GetBool("include_details");

            bool Matches(string name) =>
                string.IsNullOrWhiteSpace(wildcard)
                || name.IndexOf(wildcard.Trim('*'), StringComparison.OrdinalIgnoreCase) >= 0;

            var featureClasses = new List<string>();
            var tables = new List<string>();
            var rasters = new List<string>();
            var featureDatasets = new List<string>();
            var details = new List<Dictionary<string, object>>();

            using (var datastore = OpenWorkspace(path))
            {
                if (datastore is Geodatabase geodatabase)
                {
                    foreach (var definition in geodatabase.GetDefinitions<FeatureDatasetDefinition>())
                        if (Matches(definition.GetName())) featureDatasets.Add(definition.GetName());

                    foreach (var definition in geodatabase.GetDefinitions<FeatureClassDefinition>())
                    {
                        var name = definition.GetName();
                        if (!Matches(name)) continue;
                        featureClasses.Add(name);
                        if (withDetails && details.Count < 50)
                        {
                            details.Add(new Dictionary<string, object>
                            {
                                ["name"] = name,
                                ["shape_type"] = definition.GetShapeType().ToString(),
                                ["spatial_reference"] = definition.GetSpatialReference()?.Name,
                                ["fields"] = definition.GetFields().Count,
                            });
                        }
                    }

                    foreach (var definition in geodatabase.GetDefinitions<TableDefinition>())
                        if (Matches(definition.GetName())) tables.Add(definition.GetName());

                    try
                    {
                        foreach (var definition in geodatabase.GetDefinitions<RasterDatasetDefinition>())
                            if (Matches(definition.GetName())) rasters.Add(definition.GetName());
                    }
                    catch { /* not every geodatabase exposes rasters */ }
                }
                else
                {
                    // A shapefile folder has no catalog to query; the files are it.
                    foreach (var file in Directory.EnumerateFiles(path, "*.shp"))
                    {
                        var name = Path.GetFileNameWithoutExtension(file);
                        if (Matches(name)) featureClasses.Add(name);
                    }
                }
            }

            // Tables in a geodatabase include the feature classes' own tables.
            tables = tables.Except(featureClasses, StringComparer.OrdinalIgnoreCase).ToList();

            var result = new Dictionary<string, object>
            {
                ["workspace"] = path,
                ["feature_classes"] = featureClasses.OrderBy(n => n, StringComparer.Ordinal)
                                                    .Take(limit).ToList(),
                ["tables"] = tables.OrderBy(n => n, StringComparer.Ordinal).Take(limit).ToList(),
                ["rasters"] = rasters.OrderBy(n => n, StringComparer.Ordinal).Take(limit).ToList(),
                ["feature_datasets"] = featureDatasets.OrderBy(n => n, StringComparer.Ordinal)
                                                      .ToList(),
                ["total"] = featureClasses.Count + tables.Count + rasters.Count,
            };
            if (withDetails) result["details"] = details;
            return result;
        }

        private static object Describe(Params parameters)
        {
            var path = ResolvePath(parameters.Require("path"));
            var workspace = Path.GetDirectoryName(path);
            var name = Path.GetFileName(path);

            // A shapefile keeps its extension; a geodatabase dataset does not.
            if (workspace != null
                && workspace.EndsWith(".gdb", StringComparison.OrdinalIgnoreCase) == false
                && name.EndsWith(".shp", StringComparison.OrdinalIgnoreCase) == false
                && Directory.Exists(path))
            {
                throw new ArgumentException(
                    $"{path} is a workspace, not a dataset. Use list_workspace_contents.");
            }

            var info = new Dictionary<string, object> { ["path"] = path, ["name"] = name };

            using (var datastore = OpenWorkspace(workspace))
            {
                var lookup = name.EndsWith(".shp", StringComparison.OrdinalIgnoreCase)
                    ? Path.GetFileNameWithoutExtension(name)
                    : name;

                try
                {
                    using (var featureClass = (datastore as Geodatabase)?
                               .OpenDataset<FeatureClass>(lookup)
                           ?? (datastore as FileSystemDatastore)?
                               .OpenDataset<FeatureClass>(lookup))
                    {
                        var definition = featureClass.GetDefinition();
                        info["data_type"] = "FeatureClass";
                        info["shape_type"] = definition.GetShapeType().ToString();
                        info["spatial_reference"] =
                            MapHelpers.Describe(definition.GetSpatialReference());
                        info["oid_field"] = definition.GetObjectIDField();
                        info["row_count"] = featureClass.GetCount();
                        info["fields"] = definition.GetFields()
                            .Select(MapHelpers.Describe).ToList();
                        info["extent"] = MapHelpers.Describe(featureClass.GetExtent());
                    }
                }
                catch
                {
                    using (var table = (datastore as Geodatabase)?.OpenDataset<Table>(lookup))
                    {
                        if (table == null) throw;
                        var definition = table.GetDefinition();
                        info["data_type"] = "Table";
                        info["oid_field"] = definition.GetObjectIDField();
                        info["row_count"] = table.GetCount();
                        info["fields"] = definition.GetFields()
                            .Select(MapHelpers.Describe).ToList();
                    }
                }
            }
            return info;
        }

        private static object Search(Params parameters)
        {
            var needle = parameters.GetString("name", string.Empty) ?? string.Empty;
            var limit = parameters.GetInt("limit", 100);

            var roots = parameters.GetStringList("workspaces")?.Select(ResolvePath).ToList()
                        ?? DefaultSearchRoots();

            var matches = new List<Dictionary<string, object>>();
            var searched = new List<string>();

            foreach (var root in roots.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (matches.Count >= limit) break;
                if (string.IsNullOrWhiteSpace(root)) continue;
                if (!Directory.Exists(root) && !File.Exists(root)) continue;

                // Folders are searched for the geodatabases they hold as well.
                var workspaces = new List<string> { root };
                if (Directory.Exists(root)
                    && !root.EndsWith(".gdb", StringComparison.OrdinalIgnoreCase))
                {
                    try
                    {
                        workspaces.AddRange(Directory.GetDirectories(root, "*.gdb"));
                    }
                    catch { /* unreadable folder */ }
                }

                foreach (var workspace in workspaces)
                {
                    if (matches.Count >= limit) break;
                    try
                    {
                        searched.Add(workspace);
                        using (var datastore = OpenWorkspace(workspace))
                        {
                            void Collect<T>(string kind) where T : Definition
                            {
                                IReadOnlyList<T> definitions;
                                try { definitions = GetDefinitions<T>(datastore); }
                                catch { return; }
                                foreach (var definition in definitions)
                                {
                                    var name = definition.GetName();
                                    if (needle.Length > 0 && name.IndexOf(
                                            needle, StringComparison.OrdinalIgnoreCase) < 0)
                                        continue;
                                    if (matches.Count >= limit) return;
                                    matches.Add(new Dictionary<string, object>
                                    {
                                        ["name"] = name,
                                        ["type"] = kind,
                                        ["path"] = Path.Combine(workspace, name),
                                        ["workspace"] = workspace,
                                    });
                                }
                            }

                            if (datastore is Geodatabase)
                            {
                                Collect<FeatureClassDefinition>("feature_class");
                                Collect<TableDefinition>("table");
                            }
                            else
                            {
                                foreach (var file in Directory.EnumerateFiles(workspace, "*.shp"))
                                {
                                    var name = Path.GetFileNameWithoutExtension(file);
                                    if (needle.Length > 0 && name.IndexOf(
                                            needle, StringComparison.OrdinalIgnoreCase) < 0)
                                        continue;
                                    if (matches.Count >= limit) break;
                                    matches.Add(new Dictionary<string, object>
                                    {
                                        ["name"] = name,
                                        ["type"] = "shapefile",
                                        ["path"] = file,
                                        ["workspace"] = workspace,
                                    });
                                }
                            }
                        }
                    }
                    catch { /* skip anything that will not open */ }
                }
            }

            return new Dictionary<string, object>
            {
                ["query"] = parameters.GetString("name"),
                ["match_count"] = matches.Count,
                ["matches"] = matches,
                ["searched"] = searched,
            };
        }

        private static IReadOnlyList<T> GetDefinitions<T>(Datastore datastore)
            where T : Definition
        {
            // Only a geodatabase can be asked what it holds; shapefile folders
            // are enumerated by the caller.
            return datastore is Geodatabase geodatabase
                ? geodatabase.GetDefinitions<T>()
                : new List<T>();
        }

        private static List<string> DefaultSearchRoots()
        {
            var roots = new List<string>();
            var project = Project.Current;
            if (project == null) return roots;

            if (!string.IsNullOrEmpty(project.DefaultGeodatabasePath))
                roots.Add(project.DefaultGeodatabasePath);
            if (!string.IsNullOrEmpty(project.HomeFolderPath))
                roots.Add(project.HomeFolderPath);
            try
            {
                roots.AddRange(project.GetItems<FolderConnectionProjectItem>()
                    .Select(item => item.Path).Where(p => !string.IsNullOrEmpty(p)));
            }
            catch { /* no folder connections */ }
            return roots;
        }

        private static object ListFolder(Params parameters)
        {
            var folder = ResolvePath(parameters.GetString("folder"))
                         ?? Project.Current?.HomeFolderPath;
            if (folder == null || !Directory.Exists(folder))
                throw new ArgumentException($"Folder does not exist: {folder}");

            var pattern = parameters.GetString("pattern");
            var onlyData = parameters.GetBool("only_data", true);
            var recursive = parameters.GetBool("recursive");
            var limit = parameters.GetInt("limit", MaxItems);

            var option = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;
            var files = Directory.EnumerateFiles(folder, "*", option)
                .Where(path =>
                {
                    var name = Path.GetFileName(path);
                    if (!string.IsNullOrWhiteSpace(pattern)
                        && name.IndexOf(pattern, StringComparison.OrdinalIgnoreCase) < 0)
                        return false;
                    return !onlyData || DataExtensions.Any(
                        ext => name.EndsWith(ext, StringComparison.OrdinalIgnoreCase));
                })
                .Take(limit + 1).ToList();

            var folders = Directory.EnumerateDirectories(folder, "*", option)
                .Where(path => string.IsNullOrWhiteSpace(pattern)
                               || Path.GetFileName(path).IndexOf(
                                   pattern, StringComparison.OrdinalIgnoreCase) >= 0)
                .Take(limit).ToList();

            return new Dictionary<string, object>
            {
                ["folder"] = folder,
                ["files"] = files.Take(limit).ToList(),
                ["folders"] = folders,
                ["files_truncated"] = files.Count > limit,
            };
        }

        private static object GetProjectItems(Params parameters)
        {
            var project = MapHelpers.RequireProject();
            var data = new Dictionary<string, object>
            {
                ["home_folder"] = project.HomeFolderPath,
                ["default_geodatabase"] = project.DefaultGeodatabasePath,
                ["default_toolbox"] = project.DefaultToolboxPath,
            };
            try
            {
                data["folders"] = project.GetItems<FolderConnectionProjectItem>()
                    .Select(item => item.Path).ToList();
            }
            catch { data["folders"] = new List<string>(); }
            try
            {
                data["databases"] = project.GetItems<GDBProjectItem>()
                    .Select(item => new Dictionary<string, object>
                    {
                        ["name"] = item.Name,
                        ["path"] = item.Path,
                    }).ToList();
            }
            catch { data["databases"] = new List<object>(); }
            return data;
        }

        private static object AddFolderConnection(Params parameters)
        {
            var folder = ResolvePath(parameters.Require("folder"));
            if (!Directory.Exists(folder))
                throw new ArgumentException($"Folder does not exist: {folder}");

            var item = ItemFactory.Instance.Create(folder, ItemFactory.ItemType.PathItem);
            Project.Current.AddItem(item as IProjectItem);
            return new Dictionary<string, object> { ["added_folder"] = folder };
        }
    }
}
