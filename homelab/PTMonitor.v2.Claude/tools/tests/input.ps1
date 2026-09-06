# Shared synthetic-input helpers (SendInput, absolute coordinates over the virtual desktop).
Add-Type @"
using System; using System.Runtime.InteropServices;
public class In {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public MOUSEINPUT mi; public long pad1; public long pad2; }
  [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  static INPUT Mk(uint flags, int dx, int dy) { var i = new INPUT(); i.type = 0; i.mi.dwFlags = flags; i.mi.dx = dx; i.mi.dy = dy; return i; }
  // virtual-desktop absolute move
  public static void MoveTo(int x, int y) {
    int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
    int ax = (int)(((double)(x - vx) * 65535.0) / (vw - 1)), ay = (int)(((double)(y - vy) * 65535.0) / (vh - 1));
    var arr = new INPUT[] { Mk(0x0001 | 0x8000 | 0x4000, ax, ay) };
    SendInput(1, arr, Marshal.SizeOf(typeof(INPUT)));
  }
  public static void Down() { var arr = new INPUT[] { Mk(0x0002, 0, 0) }; SendInput(1, arr, Marshal.SizeOf(typeof(INPUT))); }
  public static void Up()   { var arr = new INPUT[] { Mk(0x0004, 0, 0) }; SendInput(1, arr, Marshal.SizeOf(typeof(INPUT))); }
  public static string Cursor() { POINT p; GetCursorPos(out p); return p.X + "," + p.Y; }
}
"@
