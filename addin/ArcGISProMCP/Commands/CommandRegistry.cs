namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Every command the add-in implements itself. Anything absent here is
    /// forwarded to the Python bridge, so adding a command is a matter of
    /// registering it -- the MCP tool catalog does not change either way.
    /// </summary>
    internal static class CommandRegistry
    {
        public static void RegisterAll()
        {
            SessionCommands.Register();
            LayerCommands.Register();
            DataCommands.Register();
            SymbologyCommands.Register();
            LayoutCommands.Register();
            CatalogCommands.Register();
            MapCommands.Register();
            EditCommands.Register();
            GpWrapperCommands.Register();
            ViewCommands.Register();
            RasterCommands.Register();
            GeoprocessingCommands.Register();
        }
    }
}
