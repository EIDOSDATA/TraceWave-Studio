/** @file @brief 봉인된 PCB 입력의 별도 WSL 체크포인트 엔진을 제어한다. */
#include "studio_internal.h"
#include "studio_theme.h"
#include <wx/choicdlg.h>
#include <wx/process.h>
#include <wx/txtstrm.h>
#include <wx/weakref.h>
#include <wx/wrapsizer.h>
#include <wx/timer.h>

namespace
{
/** @brief 단일 프로세스의 짧은 응답만 읽고 창이 닫혀도 엔진은 보존한다. */
class CheckpointCall final : public wxProcess
{
public:
    using Callback = std::function<void(int, const std::string&)>;

    explicit CheckpointCall(Callback done) : m_done(std::move(done))
    {
        Redirect();
    }

    void OnTerminate(int, int status) override
    {
        auto* stream = status == 0 ? GetInputStream() : GetErrorStream();
        wxTextInputStream input(*stream, wxT(" "), wxConvUTF8);
        wxString text;
        while (stream->CanRead() && text.length() < 4000)
        {
            text += input.ReadLine();
        }
        m_done(status, Utf8(text));
        delete this;
    }

private:
    Callback m_done;
};

/** @brief 프로젝트 결과로 게시하지 않는 복원 작업과 현재 확인된 상태를 표시한다. */
class CheckpointDialog final : public wxDialog
{
public:
    CheckpointDialog(wxWindow* parent, const Options& options, const Json& source)
        : wxDialog(parent, wxID_ANY, Display("FDTD 체크포인트 작업"), wxDefaultPosition, wxDefaultSize,
                   wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER), m_options(options), m_source(source)
    {
        auto* root = new wxBoxSizer(wxVERTICAL);
        const auto pad = FromDIP(10);
        root->Add(new wxStaticText(this, wxID_ANY, Display("단일 급전 / 스레드 1개 / 방사 및 필드 기록 끔")), 0, wxALL, pad);
        root->Add(new wxStaticText(this, wxID_ANY, Display("일반 해석과 별도로 U/I 시간 파형을 계산합니다. 프로젝트 결과 및 수렴 판정은 일반 해석에서 확인하십시오.")),
                  0, wxLEFT | wxRIGHT | wxBOTTOM, pad);
        auto* info = new wxTextCtrl(this, wxID_ANY, Display("설계 개정  " + source.at("revision_id").get<std::string>()
            + "\\n준비 계획  " + source.at("prepared_plan_id").get<std::string>() + "\\nXML SHA256  " + source.at("xml").at("sha256").get<std::string>()),
            wxDefaultPosition, FromDIP(wxSize(610, 85)), wxTE_READONLY | wxTE_MULTILINE);
        root->Add(info, 0, wxEXPAND | wxLEFT | wxRIGHT, pad);
        root->Add(new wxStaticText(this, wxID_ANY, Display("이 준비 입력의 체크포인트 실행")), 0, wxALL, pad);
        m_jobs = new wxChoice(this, wxID_ANY);
        m_jobs->SetName("checkpoint.jobs");
        root->Add(m_jobs, 0, wxEXPAND | wxLEFT | wxRIGHT, pad);
        m_jobs->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { Run("status"); });
        auto* actions = new wxWrapSizer(wxHORIZONTAL);
        for (const auto& [action, label] : std::vector<std::pair<std::string, std::string>>{
                 {"start", "새 엔진 시작"}, {"suspend", "체크포인트 기록 후 정지"}, {"resume", "기록에서 재개"}, {"status", "상태 확인"}, {"list", "목록 갱신"}})
        {
            auto* button = new wxButton(this, wxID_ANY, Display(label));
            button->SetName(Display("checkpoint." + action));
            StudioTheme::Button(*button);
            button->Bind(wxEVT_BUTTON, [this, action](wxCommandEvent&) { Run(action); });
            actions->Add(button, 0, wxRIGHT, FromDIP(6));
            m_buttons[action] = button;
        }
        root->Add(actions, 0, wxEXPAND | wxALL, pad);
        m_status = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 100)),
                                  wxTE_READONLY | wxTE_MULTILINE);
        m_status->SetName("checkpoint.status.text");
        root->Add(m_status, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
        root->Add(CreateStdDialogButtonSizer(wxCLOSE), 0, wxALIGN_RIGHT | wxALL, pad);
        Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { EndModal(wxID_CLOSE); }, wxID_CLOSE);
        SetSizerAndFit(root);
        CentreOnParent();
        Run("list");
    }

    void ExerciseControls()
    {
        m_testTimer.SetOwner(this);
        Bind(wxEVT_TIMER, [this](wxTimerEvent&)
        {
            if (m_busy)
            {
                return;
            }
            const auto text = m_status->GetValue();
            if (text.StartsWith(Display("체크포인트 작업 실패")))
            {
                m_smokeError = Utf8(text);
                EndModal(wxID_CANCEL);
                return;
            }
            static const std::vector<std::pair<std::string, std::string>> sequence{
                {"", "start"}, {"running", "status"}, {"running", "suspend"}, {"suspended", "resume"}, {"completed", "status"}};
            if (m_testStep == sequence.size())
            {
                m_testTimer.Stop();
                if (m_state == "completed" && text.Contains(Display("전압 표본")) && text.Contains(Display("전류 표본")))
                {
                    EndModal(wxID_OK);
                }
                else
                {
                    m_smokeError = Utf8(text);
                    EndModal(wxID_CANCEL);
                }
                return;
            }
            const auto& [expected, action] = sequence[m_testStep];
            if (m_state != expected || !m_buttons.at(action)->IsEnabled())
            {
                m_smokeError = "실제 동작을 수행할 수 없습니다. " + action + " / " + Utf8(text);
                EndModal(wxID_CANCEL);
                return;
            }
            ++m_testStep;
            auto* button = m_buttons.at(action);
            wxCommandEvent event(wxEVT_BUTTON, button->GetId());
            event.SetEventObject(button);
            button->ProcessWindowEvent(event);
        });
        m_testTimer.Start(100);
    }

    std::string m_smokeError;

private:
    /** @brief 현재 선택 작업과 가장 최근에 실제로 읽은 상태로 허용 동작을 표시한다. */
    void UpdateActions()
    {
        const bool hasJob = m_jobs->GetSelection() != wxNOT_FOUND;
        m_jobs->Enable(!m_busy);
        for (const auto& [name, button] : m_buttons)
        {
            bool enabled = (name == "start" && m_ready) || name == "list" || (name == "status" && hasJob);
            enabled = enabled || (hasJob && name == "suspend" && (m_state == "running" || m_state == "checkpointing" || m_state == "stopping"));
            enabled = enabled || (hasJob && name == "resume" && (m_state == "suspended" || (m_state == "interrupted" && m_canResume)));
            button->Enable(!m_busy && enabled);
        }
    }

    void Run(const std::string& action)
    {
        if (m_busy)
        {
            return;
        }
        const bool needsJob = action == "status" || action == "suspend" || action == "resume";
        if (needsJob && m_jobs->GetSelection() == wxNOT_FOUND)
        {
            return;
        }
        const auto& xml = m_source.at("xml");
        std::vector<std::wstring> args{m_options.python.ToStdWstring(), L"-X", L"utf8", L"-m", L"rfad.cli.pcb_checkpoint",
            Display(action).ToStdWstring(), L"--project", Display(m_source.at("project_id").get<std::string>()).ToStdWstring(),
            L"--plan", Display(m_source.at("prepared_plan_id").get<std::string>()).ToStdWstring(),
            L"--sha256", Display(xml.at("sha256").get<std::string>()).ToStdWstring(),
            L"--engine", Display(m_source.at("engine").get<std::string>()).ToStdWstring()};
        if (action == "start" || action == "list")
        {
            args.push_back(L"--xml");
            const auto workspace = std::filesystem::path(m_options.workspace.ToStdWstring());
            args.push_back((workspace / std::filesystem::u8path(xml.at("uri").get<std::string>())).native());
        }
        if (needsJob)
        {
            args.push_back(L"--job");
            args.push_back(m_jobs->GetStringSelection().ToStdWstring());
        }
        std::vector<const wchar_t*> argv;
        for (const auto& arg : args)
        {
            argv.push_back(arg.c_str());
        }
        argv.push_back(nullptr);
        wxExecuteEnv env;
        wxGetEnvMap(&env.env);
        env.env["PYTHONPATH"] = m_options.source;
        env.env["PYTHONIOENCODING"] = "utf-8";
        wxWeakRef<CheckpointDialog> self(this);
        auto* process = new CheckpointCall([self, action](int status, const std::string& text)
        {
            if (self)
            {
                self->Done(action, status, text);
            }
        });
        m_busy = true;
        UpdateActions();
        m_status->ChangeValue(Display(action == "resume" ? "복원한 엔진을 실행 중입니다. 종료 코드와 U/I 파형을 확인할 때까지 기다리십시오."
                                                       : "WSL 실행 환경에서 작업 상태를 확인 중입니다."));
        if (wxExecute(argv.data(), wxEXEC_ASYNC | wxEXEC_HIDE_CONSOLE, process, &env) == 0)
        {
            delete process;
            Done(action, 1, "설정된 Python을 실행하지 못했습니다.");
        }
    }

    void Done(const std::string& action, int code, const std::string& text)
    {
        m_busy = false;
        const auto response = Json::parse(text, nullptr, false);
        if (code != 0 || !response.is_object())
        {
            if (action == "list")
            {
                m_ready = false;
            }
            m_status->ChangeValue(Display("체크포인트 작업 실패. " + text));
            UpdateActions();
            return;
        }
        if (action == "list")
        {
            m_ready = true;
            m_jobs->Clear();
            for (const auto& item : response.at("jobs"))
            {
                m_jobs->Append(Display(item.at("job").get<std::string>()));
            }
            if (m_jobs->GetCount())
            {
                m_jobs->SetSelection(0);
                Run("status");
                return;
            }
            m_state.clear();
            m_status->ChangeValue(Display("이 준비 입력으로 시작한 체크포인트 작업이 없습니다."));
        }
        else
        {
            const auto job = Display(response.at("job").get<std::string>());
            if (m_jobs->FindString(job) == wxNOT_FOUND)
            {
                m_jobs->Append(job);
            }
            m_jobs->SetStringSelection(job);
            m_state = response.at("status").get<std::string>();
            m_canResume = response.at("can_resume") == true;
            static const std::map<std::string, std::string> labels{
                {"running", "실행 중"}, {"checkpointing", "기록 중"}, {"stopping", "정지 중"}, {"suspended", "중단됨"},
                {"resuming", "재개 중"}, {"completed", "엔진 정상 종료"}, {"interrupted", "종료 미확인"}, {"failed", "실패"}};
            auto label = labels.count(m_state) ? labels.at(m_state) : m_state;
            if (response.at("reason").is_string())
            {
                label += " / " + response.at("reason").get<std::string>();
            }
            if (response.at("samples").is_object())
            {
                label += "\\n시간 단계 " + response.at("iterations").dump() + " / 전압 표본 "
                    + response.at("samples").at("port_ut_1").dump() + " / 전류 표본 " + response.at("samples").at("port_it_1").dump();
            }
            if (response.at("directory").is_string())
            {
                label += "\\nWSL 실행 폴더  " + response.at("directory").get<std::string>();
            }
            m_status->ChangeValue(Display(label));
        }
        UpdateActions();
    }

    Options m_options;
    Json m_source;
    wxChoice* m_jobs = nullptr;
    wxTextCtrl* m_status = nullptr;
    std::map<std::string, wxButton*> m_buttons;
    std::string m_state;
    bool m_busy = false;
    bool m_canResume = false;
    bool m_ready = false;
    wxTimer m_testTimer;
    std::size_t m_testStep = 0;
};
}

/** @brief 현재 프로젝트가 소유하는 준비 입력 또는 선택한 결과가 사용한 원래 계획을 조회한다. */
void StudioFrame::OpenSolverCheckpoint(const Json& filter)
{
    if (!m_connected || m_closing || m_project.empty() || !m_options.openEmsWsl)
    {
        Log("체크포인트는 WSL2 해석 환경과 열린 프로젝트가 필요합니다.");
        return;
    }
    const auto project = m_project, epoch = m_epoch;
    Send("solver.checkpoint.sources", filter, false, Context(),
        [this, project, epoch](const Json& result)
        {
            CallAfter([this, project, epoch, result]()
            {
                if (m_closing || !m_connected || m_project != project || m_epoch != epoch)
                {
                    return;
                }
                if (result.contains("plans"))
                {
                    wxArrayString labels;
                    const bool hasResult = m_solverSamples.contains("artifact_id");
                    if (hasResult)
                    {
                        labels.Add(Display("현재 표시한 결과의 원래 준비 입력"));
                    }
                    for (const auto& plan : result.at("plans"))
                    {
                        labels.Add(Display("준비 계획 " + plan.get<std::string>()));
                    }
                    if (labels.empty())
                    {
                        Log("현재 프로젝트에서 준비를 완료한 해석 입력이 없습니다.");
                        return;
                    }
                    wxSingleChoiceDialog choice(this, Display("별도 엔진에서 실행하거나 다시 열 준비 입력을 선택하십시오."),
                                                Display("체크포인트 준비 입력"), labels);
                    if (choice.ShowModal() == wxID_OK)
                    {
                        const auto selected = choice.GetSelection();
                        if (hasResult && selected == 0)
                        {
                            OpenSolverCheckpoint(Json{{"artifact_id", m_solverSamples.at("artifact_id")}});
                        }
                        else
                        {
                            OpenSolverCheckpoint(Json{{"prepared_plan_id", result.at("plans").at(selected - (hasResult ? 1 : 0))}});
                        }
                    }
                    return;
                }
                const auto& source = result.at("sources").at(0);
                if (!source.at("reason").get<std::string>().empty())
                {
                    wxMessageBox(Display(source.at("reason").get<std::string>()), Display("체크포인트 입력 조건"), wxOK | wxICON_INFORMATION, this);
                    return;
                }
                CheckpointDialog dialog(this, m_options, source);
                const bool exercise = m_options.solverSmoke && wxFileName(m_options.solverSettings).GetFullName() == "checkpoint-ui-smoke.json";
                if (exercise)
                {
                    dialog.ExerciseControls();
                }
                const int outcome = dialog.ShowModal();
                if (exercise)
                {
                    m_smoke->FinishSmoke(outcome == wxID_OK, dialog.m_smokeError);
                }
            });
        },
        [this](const Json& error) { Log("체크포인트 준비 자료 조회 실패. " + DiagnosticMessage(error)); });
}
