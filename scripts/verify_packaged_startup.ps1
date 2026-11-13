param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,
    [Parameter(Mandatory = $true)]
    [string]$WorkflowPath,
    [ValidateSet('en', 'zh')]
    [string]$Language = 'en'
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path -LiteralPath $ExecutablePath).Path
$workflow = (Resolve-Path -LiteralPath $WorkflowPath).Path
$root = Split-Path -Parent $exe
$expectedTitle = if ($Language -eq 'en') { 'AEGIS 3.0 - Command Terminal' } else { 'AEGIS 3.0 - 战术指挥终端' }
$workflowHash = (Get-FileHash -LiteralPath $workflow).Hash
$originalPath = $env:PATH
$process = $null

if (-not ('AEGISStartupProbe' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class AEGISStartupWindow {
    public IntPtr Handle;
    public string Title;
    public string ClassName;
}
public static class AEGISStartupProbe {
    private delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int count);
    public static AEGISStartupWindow[] GetWindows(int pid) {
        var windows = new List<AEGISStartupWindow>();
        EnumWindows((hwnd, param) => {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == pid) {
                var title = new StringBuilder(1024);
                var className = new StringBuilder(256);
                GetWindowText(hwnd, title, title.Capacity);
                GetClassName(hwnd, className, className.Capacity);
                windows.Add(new AEGISStartupWindow { Handle=hwnd, Title=title.ToString(), ClassName=className.ToString() });
            }
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }
}
'@
}

try {
    # Reproduce desktop startup without developer or unrelated tool DLL paths.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    try {
        $process = Start-Process -FilePath $exe `
            -ArgumentList @('--lang', $Language, '--file', ('"' + $workflow + '"')) `
            -WorkingDirectory $env:TEMP -WindowStyle Hidden -PassThru
    } finally {
        $env:PATH = $originalPath
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) {
            throw "Application exited during startup: $($process.ExitCode)"
        }
        $windows = @([AEGISStartupProbe]::GetWindows($process.Id))
        $mainWindows = @($windows | Where-Object { $_.Title -eq $expectedTitle -and $_.ClassName -like 'Qt*' })
        if ($mainWindows.Count -eq 1) {
            break
        }
    } while ([DateTime]::UtcNow -lt $deadline)

    # An alive error-dialog process is not a successful application startup.
    if ($mainWindows.Count -ne 1) {
        throw "Expected application window, found: $(($windows.Title) -join ', ')"
    }
    Start-Sleep -Seconds 2
    $process.Refresh()
    $windows = @([AEGISStartupProbe]::GetWindows($process.Id))
    $mainWindows = @($windows | Where-Object { $_.Title -eq $expectedTitle -and $_.ClassName -like 'Qt*' })
    if ($process.HasExited -or $mainWindows.Count -ne 1) {
        throw 'Application did not remain on the main window'
    }

    $modules = @($process.Modules)
    foreach ($name in @('QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'Qt6Core.dll')) {
        $loaded = @($modules | Where-Object { $_.ModuleName -ieq $name })
        if ($loaded.Count -ne 1 -or -not $loaded[0].FileName.StartsWith(
            ($root + '\_internal\'), [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Packaged Qt module was not loaded correctly: $name"
        }
    }
    $icu = @($modules | Where-Object { $_.ModuleName -ieq 'icuuc.dll' })
    if ($icu.Count -ne 1 -or $icu[0].FileName -ine "$env:SystemRoot\System32\icuuc.dll") {
        throw 'Qt did not load the Windows ICU dependency'
    }
    if ((Get-FileHash -LiteralPath $workflow).Hash -ne $workflowHash) {
        throw 'Startup modified the workflow'
    }
    [pscustomobject]@{
        Executable = $exe
        WindowTitle = $mainWindows[0].Title
        WindowClass = $mainWindows[0].ClassName
        WindowsICU = $icu[0].FileName
        QtModulesVerified = $true
        WorkflowUnchanged = $true
        Autorun = $false
    } | ConvertTo-Json
} finally {
    $env:PATH = $originalPath
    if ($process -and -not $process.HasExited) {
        [void]$process.CloseMainWindow()
        if (-not $process.WaitForExit(3000)) {
            $current = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($current -and $current.StartTime -eq $process.StartTime -and $current.Path -eq $exe) {
                Stop-Process -Id $current.Id -Force
            }
        }
    }
}
