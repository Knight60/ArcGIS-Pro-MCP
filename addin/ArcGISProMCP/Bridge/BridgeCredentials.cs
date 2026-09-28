using System;
using System.IO;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;

namespace ArcGISProMCP.Bridge
{
    internal static class BridgeCredentials
    {
        public static string DirectoryPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ArcGIS-MCP", "security");
        public static string TokenPath => Path.Combine(DirectoryPath, "http-token.txt");
        private static readonly Lazy<string> Credential = new(Load);
        internal static string Token => Credential.Value;

        public static bool Accepts(string authorization)
        {
            if (authorization == null || authorization.Length != 71 || !authorization.StartsWith("Bearer ", StringComparison.Ordinal)) return false;
            return CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(authorization.Substring(7)), Encoding.ASCII.GetBytes(Token));
        }

        internal static void WritePrivateText(string path, string text)
        {
            path = Path.GetFullPath(path);
            RejectLinks(path);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                // Create an empty file, apply owner-only ACL, then write secrets.
                using (new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { }
                ProtectFile(temporary);
                File.WriteAllText(temporary, text, new UTF8Encoding(false));
                File.Move(temporary, path, true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        internal static void RejectLinks(string path)
        {
            if (File.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Refusing to write through a file link.");
            for (var current = new DirectoryInfo(Path.GetDirectoryName(Path.GetFullPath(path))); current != null; current = current.Parent)
                if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Refusing to write through a directory link.");
        }

        private static void ProtectFile(string path)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows user ACLs are required.");
            var sid = WindowsIdentity.GetCurrent().User ?? throw new InvalidOperationException("Missing Windows identity.");
            var acl = new FileSecurity();
            acl.SetOwner(sid);
            acl.SetAccessRuleProtection(true, false);
            acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
            new FileInfo(path).SetAccessControl(acl);
        }

        private static string Load()
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows user ACLs are required.");
            var sid = WindowsIdentity.GetCurrent().User ?? throw new InvalidOperationException("Missing Windows identity.");
            // Check ancestors before any create/write. Fail closed on junctions/symlinks.
            for (var current = new DirectoryInfo(DirectoryPath); current != null; current = current.Parent)
                if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Credential path must not contain reparse points.");
            var acl = new DirectorySecurity();
            acl.SetAccessRuleProtection(true, false);
            acl.SetOwner(sid);
            acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            var directory = new DirectoryInfo(DirectoryPath);
            if (!directory.Exists) directory.Create(acl);
            directory.SetAccessControl(acl);
            if (File.Exists(TokenPath) && (File.GetAttributes(TokenPath) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Credential must not be a link.");
            if (!File.Exists(TokenPath))
            {
                // CreateNew prevents overwriting another Pro session's credential.
                try
                {
                    using var file = new FileStream(TokenPath, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                    var bytes = Encoding.ASCII.GetBytes(Convert.ToHexString(RandomNumberGenerator.GetBytes(32)));
                    file.Write(bytes);
                }
                catch (IOException) when (File.Exists(TokenPath)) { }
            }
            var fileAcl = new FileSecurity();
            fileAcl.SetOwner(sid);
            fileAcl.SetAccessRuleProtection(true, false);
            fileAcl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
            new FileInfo(TokenPath).SetAccessControl(fileAcl);
            if (new FileInfo(TokenPath).Length != 64) throw new IOException("Invalid credential file length.");
            var token = File.ReadAllText(TokenPath, Encoding.ASCII);
            if (token.Length != 64 || !System.Text.RegularExpressions.Regex.IsMatch(token, @"\A[0-9A-F]{64}\z"))
                throw new IOException("Invalid credential file; refusing unauthenticated startup.");
            return token;
        }
    }
}
