/** @file @brief 출력 조회와 표시 상태를 프로젝트/선택 세대에 묶는다. */
#include "output_controller.h"
#include "output_workspace.h"
#include "handoff_output_view.h"
#include "output_model.h"
#include "output_pending_store.h"
#include "output_record_dialog.h"
#include "studio_support.h"
#include <wx/utils.h>
#include <filesystem>
#include <stdexcept>

OutputController::OutputController(wxWindow* parent, wxWindow* conditions, const std::string& workspace,
                                   OutputGateway gateway)
    : m_gateway(std::move(gateway)), m_workspace(workspace)
{
    m_view = new OutputWorkspace(parent, conditions);
    m_view->onRefresh = [this]()
    {
        Context();
        if (m_view->Kind() != 3)
        {
            Catalog();
        }
    };
    m_view->onSnapshot = [this]()
    {
        Capture();
    };
    m_view->onPreview = [this]()
    {
        Preview();
    };
    m_view->onBuild = [this]()
    {
        Build();
    };
    m_view->onVerify = [this]()
    {
        Verify();
    };
    m_view->onCancel = [this]()
    {
        Cancel();
    };
    m_view->onRecover = [this]()
    {
        Recover();
    };
    m_view->onOpenFolder = [this]()
    {
        try
        {
            OpenFolder();
        }
        catch (const std::exception& error)
        {
            Status("failed", error.what());
        }
    };
    m_view->onChanged = [this]()
    {
        Changed();
    };
    m_view->onSelectSnapshot = [this](const Json&)
    {
        Changed();
        Context(0, true);
    };
    m_view->onSelectJob = [this](const std::string& job)
    {
        Record(job);
    };
    m_view->onSnapshotPage = [this](int offset)
    {
        Context(offset);
    };
    m_view->onCatalogPage = [this](int offset)
    {
        Catalog(offset);
    };
    auto* handoff = m_view->Handoff();
    handoff->onPage = [this](int offset)
    {
        HandoffEvidence(offset);
    };
    handoff->onPreview = [this]()
    {
        HandoffPreview();
    };
    handoff->onBuild = [this]()
    {
        HandoffBuild();
    };
    handoff->onSave = [this]()
    {
        HandoffSave();
    };
    handoff->onReviewChanged = [this]()
    {
        m_view->SetHandoffConditions(m_view->Snapshot(), m_view->Handoff()->Review());
    };
}

OutputController::~OutputController()
{
    m_lifetime.reset();
}

OutputWorkspace* OutputController::View() const
{
    return m_view;
}

bool OutputController::Active() const
{
    return m_mutating || !m_task.Empty() || m_uncertain || m_handoffDownload.is_object();
}

bool OutputController::OwnsJob(const std::string& job) const
{
    return !job.empty() && job == m_task.Id();
}

void OutputController::OpenStep()
{
    m_view->SelectKind(1);
}

void OutputController::Reset()
{
    ++m_serial;
    ++m_contextGeneration;
    ++m_catalogGeneration;
    ++m_recordGeneration;
    m_reads = 0;
    m_mutating = false;
    m_uncertain = false;
    m_cancelRequested = false;
    m_refreshNeeded = true;
    m_pending = nullptr;
    m_previewInput = nullptr;
    m_task.Reset();
    m_handoffSnapshot = nullptr;
    m_handoffInput = nullptr;
    EndHandoffSave();
    m_view->Handoff()->ResetEvidence();
    m_view->Handoff()->SetCatalog(nullptr);
    m_view->Clear("현재 프로젝트의 출력 입력과 기록을 다시 읽어야 합니다.");
}

void OutputController::Update(const std::string& project, const std::string& revision, const std::string& epoch,
                              bool connected, bool supported, bool available, bool active, bool handoffSupported)
{
    if (project != m_project || epoch != m_epoch || (m_connected && !connected))
    {
        Reset();
        m_project = project;
        m_epoch = epoch;
        if (!project.empty())
        {
            try
            {
                m_pending = OutputPendingStore::Read(m_workspace, project);
                m_uncertain = m_pending.is_object();
            }
            catch (const std::exception& error)
            {
                m_uncertain = true;
                m_view->SetStatus(error.what());
            }
        }
    }
    m_revision = revision;
    m_connected = connected;
    m_supported = supported;
    m_handoffSupported = handoffSupported;
    m_available = connected && supported && available && !project.empty();
    m_active = active;
    m_view->ConditionsView()->Show(active);
    if (active && m_available && m_refreshNeeded)
    {
        m_refreshNeeded = false;
        Context(0, true);
        if (m_view->Kind() != 3)
        {
            Catalog();
        }
        if (m_uncertain)
        {
            Status("unresolved", "이전 출력 요청의 결과를 확인해야 합니다. 새 생성은 잠겼습니다.");
        }
    }
    if (active && (!connected || !supported || project.empty()))
    {
        m_view->SetStatus(!connected   ? "서비스 연결이 필요합니다. 생성 결과를 임의로 확정하지 않습니다."
                          : !supported ? "현재 서비스에는 출력 작업 공간 계약이 없습니다. 기존 CAD 출력은 유지됩니다."
                                       : "프로젝트를 열면 출력 입력과 기록을 선택할 수 있습니다.");
    }
    Actions();
}

void OutputController::Actions()
{
    bool reviewed = m_previewInput.is_object() && m_view->Input() == m_previewInput;
    if (reviewed && m_view->Kind() != 1)
    {
        reviewed = OutputUi::MatchesPreview(m_view->Preview(), m_previewInput);
    }
    m_view->SetAvailable(m_available, m_reads > 0 || m_mutating || !m_task.Empty() || m_handoffDownload.is_object(),
                         reviewed, !m_task.Empty() && !m_cancelRequested, m_uncertain);
    m_view->SetHandoffAvailable(m_available && m_handoffSupported && m_reads == 0 && !Active());
}

void OutputController::Status(const std::string& state, const std::string& message)
{
    m_view->SetStatus(message);
    if (onStatus)
    {
        onStatus(state, message);
    }
}

void OutputController::Read(const std::string& method, const Json& input, std::function<void(const Json&)> completed,
                            std::function<void(const Json&)> failed)
{
    if (!m_available || m_reads >= 8)
    {
        if (failed)
        {
            failed({{"code", "E_RESOURCE"}, {"message", "출력 조회를 지금 접수할 수 없습니다."}});
        }
        else
        {
            Status("failed", "출력 조회를 지금 접수할 수 없습니다.");
        }
        return;
    }
    ++m_reads;
    Actions();
    const auto serial = m_serial;
    const std::weak_ptr<int> lifetime = m_lifetime;
    const auto finish = [this, lifetime, serial, completed, failed](const Json& value, bool success)
    {
        if (lifetime.expired() || serial != m_serial)
        {
            return;
        }
        --m_reads;
        try
        {
            if (success)
            {
                completed(value);
            }
            else if (failed)
            {
                failed(value);
            }
            else
            {
                Status("failed", DiagnosticMessage(value));
            }
        }
        catch (const std::exception& error)
        {
            Status("failed", std::string("출력 응답을 수용하지 못했습니다: ") + error.what());
        }
        Actions();
    };
    m_gateway(
        method, input, false,
        [finish](const Json& value)
        {
            finish(value, true);
        },
        [finish](const Json& value)
        {
            finish(value, false);
        },
        "", "");
}

void OutputController::Context(int offset, bool resetOptions)
{
    const auto generation = ++m_contextGeneration;
    Json input{{"snapshot_offset", offset}};
    if (m_view->Snapshot().is_object())
    {
        input["snapshot"] = m_view->Snapshot();
    }
    Read("export.context", input,
         [this, generation, resetOptions, offset](const Json& result)
         {
             if (generation != m_contextGeneration)
             {
                 return;
             }
             if (result.at("project_id") != m_project || !result.at("snapshots").is_array() ||
                 result.at("snapshots").size() > 25 || result.at("snapshot_offset") != offset)
             {
                 throw std::runtime_error("출력 입력 목록의 프로젝트 또는 페이지가 다릅니다.");
             }
             m_view->SetContext(result, resetOptions);
             if (m_view->Kind() == 3)
             {
                 HandoffSync();
                 return;
             }
             if (!Active() && !m_view->Record().is_object() && !m_view->Preview().is_object())
             {
                 const std::string message =
                     m_view->Snapshot().is_object() ? "고정 입력을 선택했습니다. 출력 형식과 포함 범위를 검토하세요."
                     : result.value("snapshot_total", 0) == 0
                         ? "보존된 고정 입력이 없습니다. 현재 개정을 고정하여 출력 검토를 시작하세요."
                         : "보존된 고정 입력을 선택하거나 현재 개정을 고정하세요.\n과거 파일은 출력 기록에서 "
                           "선택합니다.";
                 m_view->ClearPreview(message);
                 Status("idle", message);
             }
         });
}

void OutputController::Catalog(int offset, const std::string& preferred)
{
    const auto generation = ++m_catalogGeneration;
    Read("export.list", {{"offset", offset}},
         [this, generation, offset, preferred](const Json& result)
         {
             if (generation != m_catalogGeneration)
             {
                 return;
             }
             if (result.at("project_id") != m_project || result.at("offset") != offset ||
                 !result.at("items").is_array() || result.at("items").size() > 25)
             {
                 throw std::runtime_error("출력 이력의 프로젝트 또는 페이지가 다릅니다.");
             }
             m_view->SetCatalog(result, preferred);
         });
}

void OutputController::Record(const std::string& job)
{
    const auto generation = ++m_recordGeneration;
    m_previewInput = nullptr;
    m_view->ClearRecord("선택한 출력의 파일과 검수 기록을 조회합니다. 현재 미리보기와 별개입니다.");
    Read("export.get", {{"job_id", job}},
         [this, generation, job](const Json& result)
         {
             if (generation != m_recordGeneration)
             {
                 return;
             }
             if (result.at("project_id") != m_project || result.at("job_id") != job)
             {
                 throw std::runtime_error("출력 기록의 프로젝트 또는 작업이 다릅니다.");
             }
             const auto value = result.value("result", Json(nullptr));
             if (value.is_object() && value.at("snapshot").at("project_id") != m_project)
             {
                 throw std::runtime_error("출력 결과의 고정 입력 소유권이 다릅니다.");
             }
             m_view->SetRecord(result, Display(m_workspace));
             Status(result.value("state", ""), "선택한 보존 출력의 파일과 검수 기록을 읽었습니다.");
         });
}

void OutputController::Changed()
{
    m_previewInput = nullptr;
    m_view->ClearRecord("출력 입력이나 옵션이 바뀌었습니다. 다시 검토하세요.");
    if (m_view->Kind() == 3)
    {
        if (m_view->Snapshot() != m_handoffSnapshot)
        {
            m_view->Handoff()->ResetEvidence();
            m_handoffInput = nullptr;
        }
        m_view->SetHandoffConditions(m_view->Snapshot(), m_view->Handoff()->Review());
        HandoffSync();
    }
    Actions();
}

void OutputController::Capture()
{
    if (!m_available || Active() || m_reads > 0)
    {
        return;
    }
    m_previewInput = nullptr;
    m_view->ClearRecord("현재 개정의 출력 입력을 고정하고 있습니다.");
    Start("snapshot.create", {{"expected_revision", m_revision}, {"description", "GUI 출력 검토 입력"}});
}

void OutputController::Preview()
{
    if (!m_available || Active() || m_reads > 0 || !m_view->Snapshot().is_object())
    {
        return;
    }
    m_previewInput = nullptr;
    m_view->ClearRecord("선택한 고정 입력의 출력 내용을 검토하고 있습니다.");
    Start("export.preview", m_view->PreviewInput());
}

void OutputController::Build()
{
    if (!m_available || Active() || m_reads > 0 || !m_previewInput.is_object() || m_view->Input() != m_previewInput)
    {
        return;
    }
    Json input = m_previewInput;
    if (m_view->Kind() != 1)
    {
        if (!OutputUi::MatchesPreview(m_view->Preview(), input))
        {
            return;
        }
        input["review_hash"] = m_view->Preview().at("review_hash");
    }
    OutputRecordDialog dialog(m_view, m_view->Preview(), true);
    if (dialog.ShowModal() != wxID_OK)
    {
        return;
    }
    if (!m_available || Active() || m_view->Input() != m_previewInput)
    {
        return;
    }
    Start("export.build", input);
}

void OutputController::Verify()
{
    if (!m_available || Active() || m_reads > 0 || !m_view->Record().is_object())
    {
        return;
    }
    const auto& record = m_view->Record();
    if (!record.value("can_verify", false) || !record.value("manifest_sha256", Json(nullptr)).is_string())
    {
        return;
    }
    Start("export.verify", {{"job_id", record.at("job_id")}, {"manifest_sha256", record.at("manifest_sha256")}});
}

void OutputController::OpenFolder()
{
    const auto& record = m_view->Record();
    if (!record.is_object() || !record.value("result", Json(nullptr)).is_object())
    {
        return;
    }
    for (const auto& artifact : record.at("result").value("artifacts", Json::array()))
    {
        if (artifact.value("role", "") != "manifest")
        {
            continue;
        }
        const auto relative = std::filesystem::u8path(artifact.at("uri").get<std::string>());
        if (relative.is_absolute() || relative.has_root_name())
        {
            throw std::runtime_error("출력 경로는 작업 영역 상대 경로여야 합니다.");
        }
        for (const auto& part : relative)
        {
            if (part == "..")
            {
                throw std::runtime_error("출력 경로가 작업 영역을 벗어났습니다.");
            }
        }
        const auto directory = std::filesystem::path(Display(m_workspace).ToStdWstring()) / relative.parent_path();
        if (!wxLaunchDefaultApplication(wxString(directory.native())))
        {
            Status("failed", "완료 출력 폴더를 열지 못했습니다.");
        }
        return;
    }
}
