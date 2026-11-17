/** @file @brief STEP 원본 패키지의 표시 mesh만 읽고 형상 생성은 worker에 위임한다. */
#include "step_output_view.h"
#include "model_view.h"
#include "output_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>

StepOutputView::StepOutputView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL),
      m_displayRetry(this)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("STEP 생성과 검수"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    m_model = new ModelView(this);
    m_model->SetMinSize(FromDIP(wxSize(270, 315)));
    body->Add(m_model, 1, wxEXPAND | wxRIGHT, FromDIP(12));
    auto* tools = new wxBoxSizer(wxVERTICAL);
    tools->Add(
        new wxStaticText(this, wxID_ANY,
                         Display("출력 단위\nmm\n\n기준 좌표\n프로젝트 원점\n\nSTEP profile\nAP242 / 명시 기계 형상")),
        0, wxALL, FromDIP(8));
    const auto button = [this, tools](const char* text, bool primary = false)
    {
        auto* result = new wxButton(this, wxID_ANY, Display(text));
        StudioTheme::Button(*result, primary);
        result->SetMinSize(FromDIP(wxSize(225, 36)));
        tools->Add(result, 0, wxEXPAND | wxALL, FromDIP(4));
        return result;
    };
    m_preview = button("STEP 포함 범위 검토", true);
    m_build = button("검토한 STEP 생성");
    m_verify = button("새 reader로 다시 검수");
    m_details = button("파일 / 검수 기록");
    body->Add(tools, 0, wxEXPAND);
    layout->Add(body, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_scope =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 140)), wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_scope);
    m_scope->SetMinSize(FromDIP(wxSize(280, 140)));
    for (const auto& column :
         std::vector<std::pair<const char*, int>>{{"대상", 240}, {"포함", 130}, {"상태 / 이유", 520}})
    {
        m_scope->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_scope, 0, wxEXPAND | wxALL, FromDIP(12));
    m_notice = new wxStaticText(
        this, wxID_ANY,
        Display("생성과 독립 검수는 별개입니다. 새 reader도 같은 OCCT 커널이면 커널 독립 검증이 아닙니다."));
    layout->Add(m_notice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    SetSizer(layout);
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onPreview)
                        {
                            onPreview();
                        }
                    });
    m_build->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      if (onBuild)
                      {
                          onBuild();
                      }
                  });
    m_verify->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onVerify)
                       {
                           onVerify();
                       }
                   });
    m_details->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onDetails)
                        {
                            onDetails();
                        }
                    });
    m_model->onStatus = [this](const std::string& message)
    {
        m_notice->SetLabel(Display(message));
    };
    Bind(
        wxEVT_TIMER,
        [this](wxTimerEvent&)
        {
            LoadQueued();
        },
        m_displayRetry.GetId());
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Layout();
             FitInside();
             event.Skip();
         });
    SetAvailable(false, false, false, false);
}

void StepOutputView::SetPreview(const Json& review)
{
    m_scope->DeleteAllItems();
    const auto add = [this](const std::string& label, const std::string& included, const std::string& reason)
    {
        const long row = m_scope->InsertItem(m_scope->GetItemCount(), Display(label));
        m_scope->SetItem(row, 1, Display(included));
        m_scope->SetItem(row, 2, Display(reason));
    };
    for (const auto& item : review.value("inclusions", Json::array()))
    {
        add(OutputUi::Text(item.value("label", item.value("name", Json(nullptr)))), "포함",
            OutputUi::Text(item.value("reason", Json(nullptr)), "명시 기하"));
    }
    if (m_scope->GetItemCount() == 0)
    {
        for (const auto& field : std::vector<std::pair<const char*, const char*>>{{"layer_count", "명시 적층"},
                                                                                  {"shape_count", "도체 형상"},
                                                                                  {"surface_count", "표면층"},
                                                                                  {"environment_count", "외부 물체"}})
        {
            if (review.contains(field.first))
            {
                add(field.second, OutputUi::Text(review.at(field.first)) + "개", "출력에 포함되는 원본 개수");
            }
        }
    }
    for (const auto& item : review.value("omissions", Json::array()))
    {
        add(item.is_object() ? OutputUi::Text(item.value("label", item.value("name", Json(nullptr))), "원본 항목")
                             : "원본 항목",
            "제외", OutputUi::Issues(Json::array({item})));
    }
    m_notice->SetLabel(Display("고정 입력의 STEP 포함 범위를 검토했습니다. 생성 후 새 reader 검수는 별도입니다."));
}

void StepOutputView::SetResult(const Json& result, const wxString& workspace)
{
    m_displayRetry.Stop();
    m_pendingDisplay.Clear();
    m_workspace = workspace;
    for (const auto& artifact : result.value("artifacts", Json::array()))
    {
        if (artifact.value("role", "") == "display_mesh" && artifact.value("sha256", "") != m_loadedHash)
        {
            m_pendingDisplay.Replace({{"artifact", artifact}, {"snapshot", result.at("snapshot")}});
            m_displayRetry.Start(30);
            LoadQueued();
            break;
        }
    }
    const auto verification = result.value("verification", Json::object());
    std::string message = "생성 상태: " + OutputUi::State(result.value("status", "not_assessed"));
    if (verification.is_object())
    {
        message += " / " + OutputUi::State(verification.value("status", "not_assessed"));
        if (verification.value("fresh_reader_process", false))
        {
            message += " / 새 reader 프로세스";
        }
    }
    m_notice->SetLabel(Display(message + "\n같은 OCCT 커널의 일치는 독립 커널/제조/RF 검증을 뜻하지 않습니다."));
}

void StepOutputView::LoadQueued()
{
    if (m_pendingDisplay.Empty())
    {
        m_displayRetry.Stop();
        return;
    }
    const auto request = m_pendingDisplay.TakeWhenIdle(m_model->IsLoading());
    if (request.is_null())
    {
        return;
    }
    m_displayRetry.Stop();
    const auto& artifact = request.at("artifact");
    if (m_model->LoadArtifact(m_workspace, artifact, request.at("snapshot"), artifact.at("run_id")))
    {
        m_loadedHash = artifact.at("sha256");
    }
    else
    {
        m_notice->SetLabel(
            Display("선택한 3D 표시를 읽지 못했습니다. 같은 출력 기록을 다시 선택하세요. 출력 파일은 보존됩니다."));
    }
}

void StepOutputView::Clear(const std::string& message)
{
    m_displayRetry.Stop();
    m_pendingDisplay.Clear();
    m_model->Clear();
    m_loadedHash.clear();
    m_scope->DeleteAllItems();
    m_notice->SetLabel(Display(message));
}

void StepOutputView::SetAvailable(bool available, bool busy, bool reviewed, bool canVerify)
{
    m_preview->Enable(available && !busy);
    m_build->Enable(available && !busy && reviewed);
    m_verify->Enable(available && !busy && canVerify);
    m_details->Enable(!busy && canVerify);
}
