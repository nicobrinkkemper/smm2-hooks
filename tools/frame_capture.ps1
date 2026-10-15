# Frame-exact capture of the Eden window, paired with the mod's frame hold
# (src/hold.cpp). For each frame the game holds: wait for the present, grab the
# window, save <Out>\<frame>.png, ack the frame so the game runs one more.
param([string]$Sd, [string]$Out, [int]$Count = 600, [int]$SettleMs = 40)
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Drawing;
public class FrameCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public static Bitmap Capture(IntPtr hwnd) {
        RECT r; GetClientRect(hwnd, out r);
        Bitmap bmp = new Bitmap(r.Right - r.Left, r.Bottom - r.Top);
        using (Graphics g = Graphics.FromImage(bmp)) {
            IntPtr hdc = g.GetHdc();
            PrintWindow(hwnd, hdc, 3);   // PW_CLIENTONLY | PW_RENDERFULLCONTENT
            g.ReleaseHdc(hdc);
        }
        return bmp;
    }
}
'@
$held = Join-Path $Sd "held.bin"
$ack = Join-Path $Sd "ack.bin"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
function Read-Held {
    try { $b = [IO.File]::ReadAllBytes($held); if ($b.Length -ge 4) { return [BitConverter]::ToUInt32($b, 0) } } catch {}
    return -1
}
function Write-Ack([uint32]$v) {
    for ($i = 0; $i -lt 50; $i++) { try { [IO.File]::WriteAllBytes($ack, [BitConverter]::GetBytes($v)); return } catch { Start-Sleep -Milliseconds 2 } }
}
$last = -1; $n = 0; $hwnd = [IntPtr]::Zero
try {
    while ($n -lt $Count) {
        $f = Read-Held
        if ($f -lt 0 -or $f -eq $last) { Start-Sleep -Milliseconds 2; continue }
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = (Get-Process -Name eden | Select-Object -First 1).MainWindowHandle }
        Start-Sleep -Milliseconds $SettleMs
        $bmp = [FrameCap]::Capture($hwnd)
        $bmp.Save((Join-Path $Out ("{0:D6}.png" -f $f)), [Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        $last = $f; $n++
        Write-Ack ([uint32]$f)
        if ($n % 100 -eq 0) { Write-Host "captured $n (frame $f)" }
    }
} finally {
    Write-Ack ([uint32]::MaxValue)   # let the game run free again
}
Write-Host "done: $n frames"
