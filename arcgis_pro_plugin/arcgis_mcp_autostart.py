"""Legacy Python autostart is retired in the hardened distribution.

Intentionally does not read config, import external code, start threads or open
sockets. Remove an old .pth installation using its original installer.
"""
def main():
    return None

main()
