#include <wx/wx.h>
#include <wx/cmdline.h>
#include <wx/splitter.h>
#include <wx/treectrl.h>
#include <wx/filename.h>
#include <nlohmann/json.hpp>
#include <objbase.h>

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <utility>

#include "service_client.h"

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

namespace
{
int ExitCode = 0;

/** @brief JSON과 화면 사이의 문자열을 명시적 UTF-8로 변환한다. */
std::string Utf8(const wxString& text)
{
    const wxScopedCharBuffer buffer = text.utf8_str();
    return std::string(buffer.data(), buffer.length());
}

wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief 서버가 요구하는 정규 소문자 UUID를 생성한다. */
std::string Uuid()
{
    GUID identifier{};
    if (FAILED(CoCreateGuid(&identifier)))
    {
        throw std::runtime_error("UUID creation failed");
    }
    char buffer[37]{};
    std::snprintf(buffer, sizeof(buffer), "%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        static_cast<unsigned long>(identifier.Data1), identifier.Data2, identifier.Data3,
        identifier.Data4[0], identifier.Data4[1], identifier.Data4[2], identifier.Data4[3],
        identifier.Data4[4], identifier.Data4[5], identifier.Data4[6], identifier.Data4[7]);
    return buffer;
}

struct Options
{
    wxString python;
    wxString source;
    wxString workspace;
    wxString smokeReport;
    bool smoke = false;
};

enum
{
    IdCreate = wxID_HIGHEST + 1,
    IdOpen,
    IdSave,
    IdSnapshot,
    IdApply,
    IdTimer,
    IdShutdown
};
}

/** @brief 도메인 명령을 복제하지 않고 서비스와 연결하는 최소 편집 창이다. */
class StudioFrame final : public wxFrame
{
public:
    explicit StudioFrame(Options options)
        : wxFrame(nullptr, wxID_ANY, Display("TraceWave Studio"), wxDefaultPosition, wxSize(1050, 700)),
          m_options(std::move(options)), m_timer(this, IdTimer), m_started(Clock::now())
    {
        BuildInterface();
        Bind(wxEVT_TIMER, &StudioFrame::OnTimer, this, IdTimer);
        Bind(wxEVT_CLOSE_WINDOW, &StudioFrame::OnClose, this);
        Bind(wxEVT_THREAD, &StudioFrame::OnShutdown, this, IdShutdown);
        m_timer.Start(50);
        CallAfter([this]()
        {
            Connect();
        });
    }

private:
    struct Pending
    {
        Clock::time_point sent;
        std::function<void(const Json&)> success;
    };

    void BuildInterface()
    {
        auto* menu = new wxMenu;
        menu->Append(IdCreate, Display("새 프로젝트(&N)\tCtrl+N"));
        menu->Append(IdOpen, Display("프로젝트 열기(&O)\tCtrl+O"));
        menu->AppendSeparator();
        menu->Append(IdSave, Display("저장(&S)\tCtrl+S"));
        menu->Append(IdSnapshot, Display("스냅샷 만들기"));
        menu->AppendSeparator();
        menu->Append(wxID_EXIT, Display("종료"));
        auto* bar = new wxMenuBar;
        bar->Append(menu, Display("프로젝트"));
        SetMenuBar(bar);
        CreateStatusBar(2);
        SetStatusText(Display("서비스 연결 중"), 0);
        SetStatusText(Display("Windows wxWidgets / 개발용"), 1);

        auto* body = new wxPanel(this);
        auto* outer = new wxBoxSizer(wxVERTICAL);
        auto* splitter = new wxSplitterWindow(body, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxSP_LIVE_UPDATE);
        m_tree = new wxTreeCtrl(splitter, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTR_HAS_BUTTONS | wxTR_LINES_AT_ROOT);
        m_tree->AddRoot(Display("프로젝트 없음"));
        auto* properties = new wxPanel(splitter);
        auto* form = new wxBoxSizer(wxVERTICAL);
        form->Add(new wxStaticText(properties, wxID_ANY, Display("프로젝트 속성")), 0, wxALL, 12);
        auto* fields = new wxFlexGridSizer(2, 8, 8);
        fields->AddGrowableCol(1);
        fields->Add(new wxStaticText(properties, wxID_ANY, Display("이름")), 0, wxALIGN_CENTER_VERTICAL);
        m_name = new wxTextCtrl(properties, wxID_ANY);
        fields->Add(m_name, 1, wxEXPAND);
        fields->Add(new wxStaticText(properties, wxID_ANY, Display("설명")), 0, wxALIGN_TOP);
        m_description = new wxTextCtrl(properties, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(-1, 120), wxTE_MULTILINE);
        fields->Add(m_description, 1, wxEXPAND);
        form->Add(fields, 0, wxEXPAND | wxLEFT | wxRIGHT, 12);
        m_apply = new wxButton(properties, IdApply, Display("변경 적용"));
        form->Add(m_apply, 0, wxALL | wxALIGN_RIGHT, 12);
        m_revisionLabel = new wxStaticText(properties, wxID_ANY, Display("프로젝트를 만들거나 열어 시작하세요."));
        form->Add(m_revisionLabel, 0, wxEXPAND | wxALL, 12);
        properties->SetSizer(form);
        splitter->SplitVertically(m_tree, properties, 280);
        splitter->SetMinimumPaneSize(180);
        outer->Add(splitter, 1, wxEXPAND | wxALL, 8);
        outer->Add(new wxStaticText(body, wxID_ANY, Display("작업 기록")), 0, wxLEFT | wxRIGHT, 8);
        m_log = new wxTextCtrl(body, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(-1, 140), wxTE_MULTILINE | wxTE_READONLY);
        outer->Add(m_log, 0, wxEXPAND | wxALL, 8);
        body->SetSizer(outer);
        auto* root = new wxBoxSizer(wxVERTICAL);
        root->Add(body, 1, wxEXPAND);
        SetSizer(root);

        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            const wxString name = wxGetTextFromUser(Display("새 프로젝트 이름"), Display("프로젝트 만들기"), Display("새 안테나"), this);
            if (!name.empty())
            {
                OpenProject("create", "projects/" + Utf8(name), Utf8(name));
            }
        }, IdCreate);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            const wxString path = wxGetTextFromUser(Display("작업 영역에 등록된 경로 (projects/이름)"), Display("프로젝트 열기"), Display(m_path.empty() ? "projects/새 안테나" : m_path), this);
            if (!path.empty())
            {
                OpenProject("open", Utf8(path));
            }
        }, IdOpen);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            SaveProject();
        }, IdSave);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            Snapshot();
        }, IdSnapshot);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            Close();
        }, wxID_EXIT);
        Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            ApplyProperties();
        }, IdApply);
        UpdateControls();
    }

    void Log(const std::string& text)
    {
        m_log->AppendText(Display(text) + "\n");
        if (m_log->GetLastPosition() > 20000)
        {
            m_log->Remove(0, m_log->GetLastPosition() - 16000);
        }
    }

    void UpdateControls()
    {
        const bool ready = m_connected && !m_busy;
        GetMenuBar()->Enable(IdCreate, ready);
        GetMenuBar()->Enable(IdOpen, ready);
        GetMenuBar()->Enable(IdSave, ready && !m_project.empty());
        GetMenuBar()->Enable(IdSnapshot, ready && !m_project.empty());
        m_name->Enable(ready && !m_project.empty());
        m_description->Enable(ready && !m_project.empty());
        m_apply->Enable(ready && !m_project.empty());
    }

    void Failure(const std::string& message, bool disconnected = false)
    {
        Log(message);
        m_busy = false;
        m_activeJob.clear();
        m_jobPending = false;
        m_pending.clear();
        if (disconnected)
        {
            m_connected = false;
        }
        SetStatusText(Display(disconnected ? "서비스 연결 끊김" : "작업 실패"), 0);
        UpdateControls();
        if (m_options.smoke)
        {
            FinishSmoke(false, message);
        }
    }

    void Connect()
    {
        if (m_closing || m_finishing)
        {
            return;
        }
        std::string error;
        if (!m_client.Start(m_options.python.ToStdWstring(), m_options.source.ToStdWstring(), m_options.workspace.ToStdWstring(), error))
        {
            Failure(error, true);
            return;
        }
        Send("capabilities.get", Json::object(), false, Json::object(), [this](const Json& result)
        {
            if (!result.at("idempotency_policy").value("mutations_enabled", false))
            {
                Failure("Service does not enable project mutations.", true);
                return;
            }
            m_epoch = result.at("idempotency_policy").at("request_key_epoch").get<std::string>();
            ++m_serviceSessions;
            m_connected = true;
            m_busy = false;
            SetStatusText(Display("준비됨"), 0);
            Log("프로젝트 서비스에 연결했습니다.");
            UpdateControls();
            if (m_options.smoke)
            {
                if (m_smokeStage == 4)
                {
                    OpenProject("open", m_smokePath);
                }
                else
                {
                    m_smokePath = "projects/gui-" + Uuid();
                    OpenProject("create", m_smokePath, "GUI 초기 프로젝트");
                }
            }
        });
    }

    void Send(const std::string& method, const Json& input, bool mutation, const Json& context, std::function<void(const Json&)> success)
    {
        if (m_pending.size() >= 16)
        {
            Failure("GUI request queue is full.");
            return;
        }
        const std::string id = Uuid();
        Json params{{"contract_version", "rfad.api/2.0"}, {"context", context}, {"input", input}};
        if (mutation)
        {
            params["request_key"] = Uuid();
            params["request_key_epoch"] = m_epoch;
        }
        Json request{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", params}};
        m_pending.emplace(id, Pending{Clock::now(), std::move(success)});
        if (!m_client.Send(request.dump()))
        {
            m_pending.erase(id);
            Failure("Cannot queue service request. No automatic retry is performed.", true);
        }
    }

    Json Context() const
    {
        return Json{{"project_id", m_project}};
    }

    void WaitJob(const Json& task, std::function<void(const Json&)> completed)
    {
        m_activeJob = task.at("job_id").get<std::string>();
        m_jobComplete = std::move(completed);
        m_jobPending = false;
        m_lastPoll = Clock::time_point{};
        SetStatusText(Display("작업 처리 중"), 0);
    }

    void OpenProject(const std::string& mode, const std::string& path, const std::string& name = "")
    {
        m_busy = true;
        UpdateControls();
        Json input{{"open_mode", mode}, {"path", path}};
        if (mode == "create")
        {
            input["name"] = name;
        }
        Send("project.open", input, true, Json::object(), [this, path](const Json& task)
        {
            WaitJob(task, [this, path](const Json& result)
            {
                m_project = result.at("project_id").get<std::string>();
                m_revision = result.at("revision_id").get<std::string>();
                m_path = path;
                m_document = result.at("document");
                RefreshProject();
                Ready("프로젝트를 열었습니다.");
                if (m_options.smoke && m_smokeStage == 0)
                {
                    m_smokeStage = 1;
                    m_name->SetValue(Display("GUI 변경된 프로젝트"));
                    m_description->SetValue(Display("한글 설명 및 공백 경로 검증"));
                    ApplyProperties();
                }
                else if (m_options.smoke && m_smokeStage == 4)
                {
                    if (m_document.at("metadata").at("name") != "GUI 변경된 프로젝트" ||
                        m_document.at("metadata").at("description") != "한글 설명 및 공백 경로 검증" ||
                        result.at("saved_revision") != m_revision || m_savedRevision != m_revision)
                    {
                        FinishSmoke(false, "Reopened values do not match saved revision.");
                        return;
                    }
                    m_smokeStage = 5;
                    FinishSmoke(true, "");
                }
            });
        });
    }

    void RefreshProject()
    {
        m_name->SetValue(Display(m_document.at("metadata").at("name").get<std::string>()));
        m_description->SetValue(Display(m_document.at("metadata").at("description").get<std::string>()));
        m_revisionLabel->SetLabel(Display("설계 버전: " + m_revision));
        m_tree->DeleteAllItems();
        const wxTreeItemId root = m_tree->AddRoot(m_name->GetValue());
        const wxTreeItemId parameters = m_tree->AppendItem(root, Display("매개변수"));
        for (const auto& item : m_document.at("parameters").items())
        {
            const Json& parameter = item.value();
            const Json& quantity = parameter.at("quantity");
            const std::string value = quantity.at("value_si").is_null() ? "미정" : quantity.at("value_si").dump() + " (SI)";
            m_tree->AppendItem(parameters, Display(parameter.at("name").get<std::string>() + ": " + value));
        }
        const std::pair<const char*, const char*> groups[] = {
            {"materials", "재료"}, {"stackup", "적층"}, {"nets", "네트"}, {"geometry", "형상"}, {"ports", "포트"}
        };
        for (const auto& group : groups)
        {
            const wxTreeItemId category = m_tree->AppendItem(root, Display(group.second));
            for (const auto& item : m_document.at(group.first).items())
            {
                m_tree->AppendItem(category, Display(item.value().value("name", item.key())));
            }
        }
        m_tree->Expand(root);
        m_tree->Expand(parameters);
    }

    void Command(const std::string& type, Json payload, std::function<void()> completed)
    {
        Json input{{"expected_revision", m_revision}, {"command_id", Uuid()}, {"type", type}, {"payload", std::move(payload)}};
        Send("project.apply_command", input, true, Context(), [this, completed](const Json& result)
        {
            m_revision = result.at("new_revision").get<std::string>();
            completed();
        });
    }

    void ApplyProperties()
    {
        if (m_project.empty())
        {
            return;
        }
        m_busy = true;
        UpdateControls();
        const std::string name = Utf8(m_name->GetValue());
        const std::string description = Utf8(m_description->GetValue());
        auto applyDescription = [this, name, description]()
        {
            m_document["metadata"]["name"] = name;
            auto done = [this, description]()
            {
                m_document["metadata"]["description"] = description;
                RefreshProject();
                Ready("프로젝트 속성을 변경했습니다.");
                if (m_options.smoke && m_smokeStage == 1)
                {
                    m_smokeStage = 2;
                    SaveProject();
                }
            };
            if (m_document["metadata"]["description"] != description)
            {
                Command("metadata.describe", Json{{"description", description}}, done);
            }
            else
            {
                done();
            }
        };
        if (m_document["metadata"]["name"] != name)
        {
            Command("metadata.rename", Json{{"name", name}}, applyDescription);
        }
        else
        {
            applyDescription();
        }
    }

    void SaveProject()
    {
        m_busy = true;
        UpdateControls();
        Send("project.save", Json{{"expected_revision", m_revision}}, true, Context(), [this](const Json& task)
        {
            WaitJob(task, [this](const Json& result)
            {
                m_savedRevision = result.at("saved_revision").get<std::string>();
                Ready("현재 설계 버전을 저장했습니다.");
                if (m_options.smoke && m_smokeStage == 2)
                {
                    m_smokeStage = 3;
                    Snapshot();
                }
            });
        });
    }

    void Snapshot()
    {
        m_busy = true;
        UpdateControls();
        Send("snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI에서 생성한 스냅샷"}}, true, Context(), [this](const Json& task)
        {
            WaitJob(task, [this](const Json& result)
            {
                m_snapshot = result.at("snapshot_id").get<std::string>();
                Ready("스냅샷을 만들었습니다: " + m_snapshot);
                if (m_options.smoke && m_smokeStage == 3)
                {
                    m_smokeStage = 4;
                    m_connected = false;
                    m_transportFailed = false;
                    m_restarting = true;
                    BeginShutdown();
                }
            });
        });
    }

    void Ready(const std::string& message)
    {
        m_busy = false;
        SetStatusText(Display("준비됨"), 0);
        Log(message);
        UpdateControls();
    }

    void OnTimer(wxTimerEvent&)
    {
        if (m_finishing || m_restarting || m_closing)
        {
            return;
        }
        try
        {
            for (auto& incoming : m_client.Drain())
            {
                if (!incoming.protocol)
                {
                    Log(incoming.text);
                    continue;
                }
                const Json response = Json::parse(incoming.text);
                if (!response.is_object() || !response.contains("id") || !response["id"].is_string())
                {
                    Failure("Unexpected service protocol response.", true);
                    return;
                }
                const std::string id = response["id"].get<std::string>();
                auto found = m_pending.find(id);
                if (found == m_pending.end())
                {
                    continue;
                }
                auto callback = std::move(found->second.success);
                m_pending.erase(found);
                if (response.contains("error"))
                {
                    const Json& error = response.at("error");
                    Failure(error.value("message", std::string("Service error")));
                    return;
                }
                callback(response.at("result"));
                if (m_finishing || m_restarting || m_closing)
                {
                    return;
                }
            }
            const std::string transportError = m_client.Error();
            if (!transportError.empty() && !m_transportFailed)
            {
                m_transportFailed = true;
                Failure(transportError, true);
                return;
            }
            const auto now = Clock::now();
            for (const auto& pending : m_pending)
            {
                if (now - pending.second.sent > std::chrono::seconds(30))
                {
                    Failure("Service response timeout. Reopen and inspect durable state before resubmitting.", true);
                    return;
                }
            }
            if (!m_activeJob.empty() && !m_jobPending && now - m_lastPoll >= std::chrono::milliseconds(100))
            {
                m_jobPending = true;
                m_lastPoll = now;
                Send("job.status", Json{{"job_id", m_activeJob}}, false, Json::object(), [this](const Json& result)
                {
                    m_jobPending = false;
                    const std::string state = result.at("state").get<std::string>();
                    if (state == "completed")
                    {
                        const Json finalResult = result.at("events").back().at("operation_result");
                        auto callback = std::move(m_jobComplete);
                        m_activeJob.clear();
                        callback(finalResult);
                    }
                    else if (state == "failed" || state == "interrupted" || state == "cancelled")
                    {
                        Failure("작업이 완료되지 않았습니다: " + state + " / " + result.at("events").back().dump());
                    }
                });
            }
            if (m_options.smoke && now - m_started > std::chrono::seconds(60))
            {
                FinishSmoke(false, "GUI smoke timeout");
            }
        }
        catch (const std::exception& error)
        {
            Failure(std::string("Protocol/UI error: ") + error.what(), true);
        }
    }

    void FinishSmoke(bool passed, const std::string& error)
    {
        if (m_finishing)
        {
            return;
        }
        m_finishing = true;
        ExitCode = passed ? 0 : 2;
        Json report{{"schema_version", "rfad.gui-smoke/0.1"}, {"passed", passed}, {"stage", m_smokeStage},
            {"project_id", m_project}, {"revision_id", m_revision}, {"saved_revision", m_savedRevision},
            {"snapshot_id", m_snapshot}, {"service_sessions", m_serviceSessions},
            {"error", error}, {"physics_tested", false}, {"frame_budget_tested", false}};
        if (!m_options.smokeReport.empty())
        {
            const std::filesystem::path path(m_options.smokeReport.ToStdWstring());
            std::error_code filesystemError;
            if (!path.parent_path().empty())
            {
                std::filesystem::create_directories(path.parent_path(), filesystemError);
            }
            std::ofstream output(path, std::ios::binary);
            output << report.dump(2) << '\n';
            if (!output)
            {
                ExitCode = 3;
            }
        }
        CallAfter([this]()
        {
            Close();
        });
    }

    void OnClose(wxCloseEvent&)
    {
        if (m_closing)
        {
            return;
        }
        m_closing = true;
        m_timer.Stop();
        Disable();
        Hide();
        if (!m_restarting)
        {
            BeginShutdown();
        }
    }

    /** @brief 화면 수명을 유지한 채 서비스 종료와 pipe join을 UI 밖에서 수행한다. */
    void BeginShutdown()
    {
        try
        {
            m_shutdown = std::thread([this]()
            {
                m_client.Stop();
                wxQueueEvent(this, new wxThreadEvent(wxEVT_THREAD, IdShutdown));
            });
        }
        catch (const std::exception& error)
        {
            m_client.Stop();
            if (m_closing)
            {
                Destroy();
            }
            else
            {
                m_restarting = false;
                Failure(std::string("Cannot start shutdown thread: ") + error.what(), true);
            }
        }
    }

    /** @brief 종료 thread가 pipe를 모두 회수한 뒤 창을 파괴하거나 smoke 연결을 재개한다. */
    void OnShutdown(wxThreadEvent&)
    {
        m_shutdown.join();
        if (m_closing)
        {
            Destroy();
        }
        else
        {
            m_restarting = false;
            Connect();
        }
    }

    Options m_options;
    ServiceClient m_client;
    std::thread m_shutdown;
    wxTimer m_timer;
    wxTreeCtrl* m_tree = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_description = nullptr;
    wxTextCtrl* m_log = nullptr;
    wxButton* m_apply = nullptr;
    wxStaticText* m_revisionLabel = nullptr;
    bool m_connected = false;
    bool m_busy = true;
    bool m_jobPending = false;
    bool m_transportFailed = false;
    bool m_finishing = false;
    bool m_restarting = false;
    bool m_closing = false;
    int m_smokeStage = 0;
    int m_serviceSessions = 0;
    Clock::time_point m_started;
    Clock::time_point m_lastPoll{};
    std::map<std::string, Pending> m_pending;
    std::function<void(const Json&)> m_jobComplete;
    Json m_document;
    std::string m_epoch;
    std::string m_project;
    std::string m_revision;
    std::string m_path;
    std::string m_activeJob;
    std::string m_savedRevision;
    std::string m_snapshot;
    std::string m_smokePath;
};

/** @brief 명시한 실행 경로로 wxWidgets GUI를 초기화한다. */
class StudioApp final : public wxApp
{
public:
    bool OnInit() override
    {
        wxCmdLineParser parser(argc, argv);
        parser.AddOption("", "python", "Python executable path");
        parser.AddOption("", "source", "rfad source directory");
        parser.AddOption("", "workspace", "Project workspace directory");
        parser.AddSwitch("", "smoke-test", "Run GUI/service smoke test and exit");
        parser.AddOption("", "smoke-report", "Smoke JSON output path");
        parser.AddSwitch("h", "help", "Show help", wxCMD_LINE_OPTION_HELP);
        if (parser.Parse() != 0)
        {
            return false;
        }
        Options options;
        parser.Found("python", &options.python);
        parser.Found("source", &options.source);
        parser.Found("workspace", &options.workspace);
        parser.Found("smoke-report", &options.smokeReport);
        options.smoke = parser.Found("smoke-test");
        if (options.python.empty() || options.source.empty() || options.workspace.empty())
        {
            wxMessageBox(Display("--python, --source, --workspace 경로를 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        if (!wxFileName(options.python).IsAbsolute() || !wxFileName(options.source).IsAbsolute() || !wxFileName(options.workspace).IsAbsolute())
        {
            wxMessageBox(Display("실행 경로는 절대 경로로 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        auto* frame = new StudioFrame(std::move(options));
        SetTopWindow(frame);
        frame->Show();
        return true;
    }

    int OnRun() override
    {
        wxApp::OnRun();
        return ExitCode;
    }
};

wxIMPLEMENT_APP(StudioApp);
