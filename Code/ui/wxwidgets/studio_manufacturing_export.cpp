/** @file @brief 선택한 KiCad 게시 기록을 제조 교환 후보 ZIP으로 변환한다. */
#include "studio_internal.h"
#include "output_controller.h"
#include "output_model.h"
#include "output_workspace.h"
#include <wx/choicdlg.h>
#include <wx/process.h>
#include <wx/txtstrm.h>
#include <wx/weakref.h>

namespace
{
/** @brief 작업 중 창을 닫아도 완료한 변환만 알리고 새 출력 경로를 보존한다. */
class ManufacturingProcess final : public wxProcess
{
public:
    ManufacturingProcess(OutputWorkspace* view, wxString destination)
        : m_view(view), m_destination(std::move(destination))
    {
        Redirect();
    }

    void OnTerminate(int, int status) override
    {
        if (m_view)
        {
            if (status == 0)
            {
                m_view->SetStatus("제조 교환 후보 ZIP을 저장했습니다. " + Utf8(m_destination));
            }
            else
            {
                wxTextInputStream input(*GetErrorStream(), wxT(" "), wxConvUTF8);
                wxString message;
                while (GetErrorStream()->CanRead() && message.length() < 2400)
                {
                    message += input.ReadLine() + " ";
                }
                m_view->SetStatus("제조 교환 후보 생성 실패. " + Utf8(message));
            }
        }
        delete this;
    }

private:
    wxWeakRef<OutputWorkspace> m_view;
    wxString m_destination;
};
}

/** @brief 게시된 보드와 manifest 해시를 고정하고 설치된 KiCad에 전달할 형식과 새 ZIP 위치를 선택한다. */
void StudioFrame::ExportManufacturing()
{
    auto* view = m_output->View();
    const auto& record = view->Record();
    const auto manifest = OutputUi::ManifestPath(record);
    if (manifest.empty() || record.value("state", "") != "completed" || record.value("format", "") != "kicad_pcb" ||
        !record.value("manifest_sha256", Json(nullptr)).is_string() ||
        record.at("result").value("profile", "") != "rfad.exchange.kicad-board/0.1")
    {
        view->SetStatus("출력 이력에서 생성이 끝난 KiCad 보드 패키지를 선택하십시오.");
        return;
    }
    const auto hash = record.at("manifest_sha256").get<std::string>();
    wxArrayString choices;
    choices.Add(Display("IPC-2581C 및 ODB++"));
    choices.Add(Display("IPC-2581C"));
    choices.Add(Display("ODB++"));
    wxSingleChoiceDialog format(this, Display("ZIP에 포함할 제조 파일을 선택하십시오."),
                                Display("제조 교환 후보 내보내기"), choices);
    format.SetSelection(0);
    if (format.ShowModal() != wxID_OK)
    {
        return;
    }
    wxFileDialog executable(this, Display("설치된 KiCad의 kicad-cli.exe 선택"), wxEmptyString, "kicad-cli.exe",
                            "KiCad CLI (kicad-cli.exe)|kicad-cli.exe", wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (executable.ShowModal() != wxID_OK)
    {
        return;
    }
    if (wxFileName(executable.GetPath()).GetFullName().CmpNoCase("kicad-cli.exe") != 0)
    {
        view->SetStatus("설치된 KiCad의 kicad-cli.exe를 선택하십시오.");
        return;
    }
    wxFileDialog output(this, Display("새 제조 교환 후보 ZIP 저장"), wxEmptyString, "manufacturing.zip",
                        "ZIP (*.zip)|*.zip", wxFD_SAVE);
    if (output.ShowModal() != wxID_OK)
    {
        return;
    }
    const auto destination = std::filesystem::path(output.GetPath().ToStdWstring());
    const auto workspace = std::filesystem::path(m_options.workspace.ToStdWstring());
    std::error_code ec;
    const auto parent = std::filesystem::canonical(destination.parent_path(), ec);
    if (ec)
    {
        view->SetStatus("ZIP을 저장할 상위 폴더에 접근할 수 없습니다.");
        return;
    }
    const auto workspaceRoot = std::filesystem::canonical(workspace, ec);
    const auto relative = parent.lexically_relative(workspaceRoot);
    if (ec || (!relative.empty() && *relative.begin() != "..") || std::filesystem::exists(destination, ec) || ec)
    {
        view->SetStatus("작업 영역 밖에 아직 존재하지 않는 ZIP 파일을 지정하십시오.");
        return;
    }
    const auto source = (workspace / std::filesystem::u8path(manifest)).parent_path();
    std::vector<std::wstring> args = {
        (m_options.exchangePython.empty() ? m_options.python : m_options.exchangePython).ToStdWstring(),
        L"-X", L"utf8", L"-m", L"rfad.adapters.exchange.manufacturing_export", L"--quiet", L"--input", source.native(),
        L"--output", destination.native(), L"--kicad-cli", executable.GetPath().ToStdWstring(), L"--manifest-sha256",
        Display(hash).ToStdWstring()};
    if (format.GetSelection() != 0)
    {
        args.push_back(L"--format");
        args.push_back(format.GetSelection() == 1 ? L"ipc2581" : L"odb");
    }
    std::vector<const wchar_t*> argv;
    for (const auto& arg : args)
    {
        argv.push_back(arg.c_str());
    }
    argv.push_back(nullptr);
    wxExecuteEnv env;
    env.cwd = m_options.source;
    auto process = std::make_unique<ManufacturingProcess>(view, output.GetPath());
    if (wxExecute(argv.data(), wxEXEC_ASYNC | wxEXEC_HIDE_CONSOLE, process.get(), &env) == 0)
    {
        view->SetStatus("제조 교환 변환기를 실행할 수 없습니다. 설정된 Python 경로를 확인하십시오.");
        return;
    }
    process.release();
    view->SetStatus("선택한 게시 기록을 KiCad에서 변환하고 있습니다.");
}
