using System;
using System.IO;
using System.Linq;
using ArcGIS.Core.Data;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Something a data command can read: a layer in the map, a standalone
    /// table, or a dataset opened straight from a path.
    ///
    /// The path case matters more than it looks. Geoprocessing writes its
    /// output to places like memory\stats or a scratch geodatabase, and the
    /// natural next step is to read it -- which failed while these commands
    /// only understood layers, even though the tools advertise that a path
    /// works anywhere a layer name does.
    ///
    /// Reads go through the layer when there is one, so a definition query and
    /// the current selection still apply.
    /// </summary>
    internal sealed class DataSource : IDisposable
    {
        private readonly BasicFeatureLayer _layer;
        private readonly Table _table;

        private DataSource(BasicFeatureLayer layer, Table table)
        {
            _layer = layer;
            _table = table;
        }

        public string Name { get; private set; }

        /// <summary>The layer this came from, or null when opened by path.</summary>
        public BasicFeatureLayer Layer => _layer;

        public TableDefinition Definition => _table.GetDefinition();

        public RowCursor Search(QueryFilter filter)
        {
            return _layer != null ? _layer.Search(filter) : _table.Search(filter, false);
        }

        public SpatialReference SpatialReference
        {
            get
            {
                if (_layer != null) return _layer.GetSpatialReference();
                return (_table as FeatureClass)?.GetDefinition()?.GetSpatialReference();
            }
        }

        public void Dispose() => _table?.Dispose();

        // --- resolution -------------------------------------------------------

        /// <summary>
        /// Resolve the layer_name parameter, which may name a layer, a
        /// standalone table, or a dataset path.
        /// </summary>
        public static DataSource Resolve(Params parameters, string key = "layer_name")
        {
            var name = parameters.Require(key);
            var map = TryResolveMap(parameters);

            if (map != null)
            {
                var layer = map.GetLayersAsFlattenedList().OfType<BasicFeatureLayer>()
                    .FirstOrDefault(l => string.Equals(l.Name, name,
                                                       StringComparison.OrdinalIgnoreCase));
                if (layer != null)
                    return new DataSource(layer, layer.GetTable()) { Name = layer.Name };

                var standalone = map.GetStandaloneTablesAsFlattenedList()
                    .FirstOrDefault(t => string.Equals(t.Name, name,
                                                       StringComparison.OrdinalIgnoreCase));
                if (standalone != null)
                    return new DataSource(null, standalone.GetTable()) { Name = standalone.Name };
            }

            var opened = TryOpenPath(name);
            if (opened != null) return opened;

            var available = map == null ? "(no map)" : string.Join(", ",
                map.GetLayersAsFlattenedList().Select(l => l.Name)
                   .Concat(map.GetStandaloneTablesAsFlattenedList().Select(t => t.Name)));
            throw new ArgumentException(
                $"No layer, table or dataset called '{name}'. Layers and tables in the "
                + $"map: {available}. A full path also works, including memory\\name.");
        }

        private static Map TryResolveMap(Params parameters)
        {
            try { return MapHelpers.ResolveMap(parameters); }
            catch { return null; }
        }

        /// <summary>Open a dataset by path, or return null if it is not one.</summary>
        private static DataSource TryOpenPath(string path)
        {
            var normalised = path.Replace('/', '\\').Trim();

            // Geoprocessing writes here constantly; "in_memory" is the older
            // spelling of the same workspace.
            foreach (var prefix in new[] { "memory\\", "in_memory\\" })
            {
                if (!normalised.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
                var dataset = normalised.Substring(prefix.Length);
                var geodatabase = new Geodatabase(new MemoryConnectionProperties());
                return Open(geodatabase, dataset, path);
            }

            var index = normalised.IndexOf(".gdb\\", StringComparison.OrdinalIgnoreCase);
            if (index > 0)
            {
                var workspace = normalised.Substring(0, index + 4);
                var dataset = normalised.Substring(index + 5);
                if (!Directory.Exists(workspace)) return null;
                var geodatabase = new Geodatabase(
                    new FileGeodatabaseConnectionPath(new Uri(workspace)));
                return Open(geodatabase, dataset, path);
            }

            if (normalised.EndsWith(".shp", StringComparison.OrdinalIgnoreCase)
                || normalised.EndsWith(".dbf", StringComparison.OrdinalIgnoreCase))
            {
                if (!File.Exists(normalised)) return null;
                var folder = Path.GetDirectoryName(normalised);
                var datastore = new FileSystemDatastore(new FileSystemConnectionPath(
                    new Uri(folder), FileSystemDatastoreType.Shapefile));
                return Open(datastore, Path.GetFileNameWithoutExtension(normalised), path);
            }

            return null;
        }

        private static DataSource Open(Datastore datastore, string dataset, string original)
        {
            try
            {
                Table table;
                try
                {
                    table = datastore is Geodatabase geodatabase
                        ? geodatabase.OpenDataset<FeatureClass>(dataset)
                        : ((FileSystemDatastore)datastore).OpenDataset<FeatureClass>(dataset);
                }
                catch
                {
                    // Not a feature class -- a plain table is just as readable.
                    table = datastore is Geodatabase gdb
                        ? gdb.OpenDataset<Table>(dataset)
                        : ((FileSystemDatastore)datastore).OpenDataset<Table>(dataset);
                }
                return new DataSource(null, table) { Name = original };
            }
            catch
            {
                datastore.Dispose();
                return null;
            }
        }
    }
}
