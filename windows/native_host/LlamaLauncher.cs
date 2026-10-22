using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;

class LlamaLauncher
{
    private const uint CREATE_BREAKAWAY_FROM_JOB = 0x01000000;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint DETACHED_PROCESS = 0x00000008;
    private const uint STARTF_USESHOWWINDOW = 0x00000001;
    private const short SW_HIDE = 0;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public uint dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcess(
        string lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFO lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr hObject);

    static int Main(string[] args)
    {
        try
        {
            string message = ReadNativeMessage();
            if (message == null || (message.IndexOf("\"start\"", StringComparison.OrdinalIgnoreCase) < 0))
            {
                WriteNativeMessage("{\"ok\":false,\"error\":\"unsupported action\"}");
                return 0;
            }

            if (IsWatchdogRunning())
            {
                WriteNativeMessage("{\"ok\":true,\"already\":true}");
                return 0;
            }

            string exeDir = AppDomain.CurrentDomain.BaseDirectory;
            string windowsDir = Path.GetFullPath(Path.Combine(exeDir, ".."));
            string repoRoot = Path.GetFullPath(Path.Combine(windowsDir, ".."));
            string trayScript = Path.Combine(windowsDir, "llm_tray.py");
            string pythonw = ResolvePythonw(repoRoot);
            if (pythonw == null)
            {
                WriteNativeMessage("{\"ok\":false,\"error\":\"pythonw.exe not found\"}");
                return 0;
            }

            bool brokeAway;
            bool startedBackend = SpawnDetached(pythonw, "-m watchdog.llm_watchdog", repoRoot, out brokeAway);
            if (File.Exists(trayScript))
            {
                bool trayBreakaway;
                SpawnDetached(pythonw, "\"" + trayScript + "\"", repoRoot, out trayBreakaway);
            }

            WriteNativeMessage(string.Format(
                "{{\"ok\":{0},\"breakaway\":{1}}}",
                startedBackend ? "true" : "false",
                brokeAway ? "true" : "false"));
            return 0;
        }
        catch (Exception ex)
        {
            string safe = (ex.Message ?? "error").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");
            WriteNativeMessage("{\"ok\":false,\"error\":\"" + safe + "\"}");
            return 0;
        }
    }

    private static string ResolvePythonw(string repoRoot)
    {
        string[] candidates = new string[]
        {
            Path.Combine(repoRoot, ".venv\\Scripts\\pythonw.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Python\\pythoncore-3.14-64\\pythonw.exe"),
            @"C:\Users\Ninjader\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe",
            Path.Combine(repoRoot, "watchdog\\.venv\\Scripts\\pythonw.exe")
        };
        foreach (string c in candidates)
        {
            if (!string.IsNullOrEmpty(c) && File.Exists(c)) return c;
        }
        return null;
    }

    private static bool IsWatchdogRunning()
    {
        try
        {
            HttpWebRequest req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8080/api/status");
            req.Method = "GET";
            req.Timeout = 1200;
            req.ReadWriteTimeout = 1200;
            using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
            {
                return (int)resp.StatusCode == 200;
            }
        }
        catch
        {
            return false;
        }
    }

    private static bool SpawnDetached(string exePath, string arguments, string workingDir, out bool brokeAway)
    {
        STARTUPINFO si = new STARTUPINFO();
        si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        si.dwFlags = STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_HIDE;
        PROCESS_INFORMATION pi;
        StringBuilder cmd = new StringBuilder("\"" + exePath + "\" " + arguments);

        uint flags = CREATE_BREAKAWAY_FROM_JOB | CREATE_NO_WINDOW | DETACHED_PROCESS;
        if (CreateProcess(exePath, cmd, IntPtr.Zero, IntPtr.Zero, false, flags, IntPtr.Zero, workingDir, ref si, out pi))
        {
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
            brokeAway = true;
            return true;
        }

        // Fallback without breakaway if parent job forbids breakaway
        brokeAway = false;
        cmd = new StringBuilder("\"" + exePath + "\" " + arguments);
        uint fallbackFlags = CREATE_NO_WINDOW | DETACHED_PROCESS;
        if (CreateProcess(exePath, cmd, IntPtr.Zero, IntPtr.Zero, false, fallbackFlags, IntPtr.Zero, workingDir, ref si, out pi))
        {
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
            return true;
        }
        return false;
    }

    private static string ReadNativeMessage()
    {
        Stream stdin = Console.OpenStandardInput();
        byte[] lenBytes = new byte[4];
        int read = 0;
        while (read < 4)
        {
            int n = stdin.Read(lenBytes, read, 4 - read);
            if (n <= 0) return null;
            read += n;
        }
        int length = BitConverter.ToInt32(lenBytes, 0);
        if (length <= 0 || length > 65536) return null;
        byte[] buf = new byte[length];
        int offset = 0;
        while (offset < length)
        {
            int n = stdin.Read(buf, offset, length - offset);
            if (n <= 0) break;
            offset += n;
        }
        return Encoding.UTF8.GetString(buf, 0, offset);
    }

    private static void WriteNativeMessage(string json)
    {
        byte[] payload = Encoding.UTF8.GetBytes(json);
        byte[] lenBytes = BitConverter.GetBytes(payload.Length);
        Stream stdout = Console.OpenStandardOutput();
        stdout.Write(lenBytes, 0, 4);
        stdout.Write(payload, 0, payload.Length);
        stdout.Flush();
    }
}
