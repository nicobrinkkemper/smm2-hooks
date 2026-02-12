param([string]$OutPath = "C:\temp\smm2_debug\capture.png")
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class WinCap {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out RECT pvAttribute, int cbAttribute);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public static Bitmap Capture(IntPtr hwnd) {
        RECT rect;
        DwmGetWindowAttribute(hwnd, 9, out rect, Marshal.SizeOf(typeof(RECT)));
        int w = rect.Right - rect.Left;
        int h = rect.Bottom - rect.Top;
        Bitmap bmp = new Bitmap(w, h);
        Graphics g = Graphics.FromImage(bmp);
        IntPtr hdc = g.GetHdc();
        PrintWindow(hwnd, hdc, 2);
        g.ReleaseHdc(hdc);
        return bmp;
    }
}
'@
$found = $null
[WinCap]::EnumWindows({
    param($h, $l)
    $sb = New-Object Text.StringBuilder 256
    [WinCap]::GetWindowText($h, $sb, 256) | Out-Null
    if ($sb.ToString() -match '^Ryujinx \d' -and [WinCap]::IsWindowVisible($h)) { $script:found = $h }
    return $true
}, [IntPtr]::Zero)
if ($found) {
    $bmp = [WinCap]::Capture($found)
    $bmp.Save($OutPath)
    Write-Host "Saved $($bmp.Width)x$($bmp.Height) to $OutPath"
} else { Write-Host "Ryujinx window not found"; exit 1 }
