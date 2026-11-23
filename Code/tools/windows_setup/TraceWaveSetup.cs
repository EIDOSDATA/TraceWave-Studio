using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("TraceWave Studio Setup")]
[assembly: AssemblyProduct("TraceWave Studio")]

internal static class TraceWaveSetup
{
    /// @brief 내장 후보를 풀어 Windows에 포함된 PowerShell 설치 단계에 전달한다.
    private static int Main(string[] arguments)
    {
        Console.OutputEncoding = Encoding.UTF8;
        string stage = Path.Combine(Path.GetTempPath(), "TraceWaveSetup-" + Guid.NewGuid().ToString("N"));
        bool quiet = Array.Exists(arguments, value => String.Equals(value, "-NoPause", StringComparison.OrdinalIgnoreCase));
        int result = 1;
        try
        {
            Directory.CreateDirectory(stage);
            string script = SaveResource(stage, "install.ps1");
            string bundle = SaveResource(stage, "studio.zip");
            string identity = SaveResource(stage, "bundle-sha256.txt");
            string powershell = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");
            var options = new List<string>
            {
                "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", script, "-Bundle", bundle, "-Identity", identity
            };
            foreach (string argument in arguments)
            {
                if (!String.Equals(argument, "-NoPause", StringComparison.OrdinalIgnoreCase))
                {
                    options.Add(argument);
                }
            }

            var start = new ProcessStartInfo(powershell, String.Join(" ", options.ConvertAll(Quote)));
            start.UseShellExecute = false;
            /// @brief 상위 셸 버전의 모듈 경로 대신 Windows PowerShell 기본 모듈을 사용한다.
            start.EnvironmentVariables.Remove("PSModulePath");
            using (Process process = Process.Start(start))
            {
                process.WaitForExit();
                result = process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
        }
        finally
        {
            foreach (string name in new[] { "install.ps1", "studio.zip", "bundle-sha256.txt" })
            {
                try
                {
                    File.Delete(Path.Combine(stage, name));
                }
                catch (IOException)
                {
                    /// @brief 다른 프로세스가 파일을 잡고 있으면 진단용 임시 사본을 남긴다.
                }
            }

            try
            {
                Directory.Delete(stage);
            }
            catch (IOException)
            {
                /// @brief 기존 디렉터리에는 재귀 삭제를 적용하지 않는다.
            }
        }

        if (!quiet && !Console.IsInputRedirected)
        {
            Console.WriteLine("Enter 키를 눌러 닫습니다.");
            Console.ReadLine();
        }

        return result;
    }

    /// @brief 실행 파일 내부의 지정 자원만 이번 실행 전용 임시 폴더에 기록한다.
    private static string SaveResource(string stage, string name)
    {
        string path = Path.Combine(stage, name);
        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        using (var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            if (source == null)
            {
                throw new InvalidDataException("설치 자원이 누락됐습니다. " + name);
            }

            source.CopyTo(output);
        }

        return path;
    }

    /// @brief Windows 명령행 규약에 따라 공백, 따옴표 및 끝 역슬래시를 보존한다.
    private static string Quote(string value)
    {
        var argument = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\')
            {
                ++slashes;
                continue;
            }

            if (character == '"')
            {
                argument.Append('\\', 2 * slashes + 1);
            }
            else
            {
                argument.Append('\\', slashes);
            }

            argument.Append(character);
            slashes = 0;
        }

        argument.Append('\\', 2 * slashes);
        return argument.Append('"').ToString();
    }
}
