# Retired: the original helper automatically discarded unsaved project changes.
[CmdletBinding()]
param([string]$Project, [switch]$Save, [int]$TimeoutSeconds = 180, [int]$CloseTimeoutSeconds = 240)
throw 'Automatic restart is disabled in the hardened build. Save your work, close ArcGIS Pro yourself, and reopen the project. No save prompt is answered automatically.'
