using ArcGISProMCP.Clients;
if (args.Length != 1 || (args[0] != "codex" && args[0] != "relay"))
    throw new ArgumentException("Usage: ClientSetup codex|relay. Writes only the selected current-user config or relay, with backup and private ACLs.");
if (args[0] == "codex") Console.WriteLine(McpClientRegistrar.Register(McpClientCatalog.ById("codex")));
else Console.WriteLine(McpClientRegistrar.EnsureStdioBridge());
