/** @file @brief 원본 solver 출력과 전체 계산 진단을 새 계산 없이 조회한다. */
#include "network_source_dialog.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>

NetworkSolverDialog::NetworkSolverDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "완료 해석 결과 등록", context, std::move(gateway)), m_context(context)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* help = new wxStaticText(this, wxID_ANY,
                                  Display("기존 완료 계산의 원본과 조건을 보존하여 공통 복소 자료로 등록합니다. 새 "
                                          "해석을 실행하거나 실측 합격으로 바꾸지 않습니다."));
    help->Wrap(FromDIP(950));
    layout->Add(help, 0, wxEXPAND | wxALL, FromDIP(12));
    m_result = new wxChoice(this, wxID_ANY);
    int index = 0;
    int selected = 0;
    for (const auto& entry : context.at("solver_results"))
    {
        if (entry.at("artifact_id") == context.value("preferred_artifact", ""))
        {
            selected = index;
        }
        ++index;
        m_result->Append(Display("계산 결과 " + std::to_string(index) + ", 표본 " + entry.at("sample_count").dump() +
                                 ", " + entry.value("profile", "")));
    }
    if (m_result->GetCount() != 0)
    {
        m_result->SetSelection(selected);
    }
    layout->Add(m_result, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    layout->Add(new wxStaticText(this, wxID_ANY, Display("등록할 결과 이름")), 0, wxLEFT | wxRIGHT, FromDIP(12));
    m_name = new wxTextCtrl(this, wxID_ANY, Display("해석 결과"));
    layout->Add(m_name, 0, wxEXPAND | wxALL, FromDIP(12));
    m_chart = new NetworkChart(this);
    layout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_details = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 140)),
                               wxTE_MULTILINE | wxTE_READONLY);
    layout->Add(m_details, 0, wxEXPAND | wxALL, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, Display("완료 자료를 선택하고 등록 후보를 검토하세요."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("등록 후보 검토"));
    m_apply = new wxButton(this, wxID_ANY, Display("새 자료로 등록"));
    StudioTheme::Button(*m_preview);
    StudioTheme::Button(*m_apply, true);
    actions->Add(m_preview, 0, wxALL, FromDIP(8));
    actions->Add(m_apply, 0, wxALL, FromDIP(8));
    actions->AddStretchSpacer();
    actions->Add(new wxButton(this, wxID_CANCEL, Display("닫기")), 0, wxALL, FromDIP(8));
    layout->Add(actions, 0, wxEXPAND);
    SetSizer(layout);
    const auto changed = [this](wxCommandEvent&)
    {
        m_dirty = true;
        InvalidateRead();
        m_review = nullptr;
        m_chart->Clear();
        m_details->Clear();
        SetStatus("입력이 바뀌었습니다. 등록 후보를 다시 검토하세요.");
        UpdateActions();
    };
    m_result->Bind(wxEVT_CHOICE, changed);
    m_name->Bind(wxEVT_TEXT, changed);
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
    UpdateActions();
}

bool NetworkSolverDialog::HasDraft() const
{
    return m_dirty || !m_review.is_null();
}

Json NetworkSolverDialog::Parameters() const
{
    return {{"name", Utf8(m_name->GetValue())},
            {"artifact_id",
             m_context.at("solver_results").at(static_cast<std::size_t>(m_result->GetSelection())).at("artifact_id")}};
}

void NetworkSolverDialog::UpdateActions()
{
    const bool ready = Editable();
    m_result->Enable(ready);
    m_name->Enable(ready);
    m_preview->Enable(ready && m_result->GetSelection() != wxNOT_FOUND && !m_name->GetValue().empty());
    m_apply->Enable(ready && m_review.is_object() && m_review.value("can_apply", false));
}

void NetworkSolverDialog::Preview()
{
    if (!m_preview->IsEnabled())
    {
        return;
    }
    Request("network.preview",
            {{"expected_revision", m_revision}, {"operation", "solver"}, {"parameters", Parameters()}}, false,
            [this](const Json& result)
            {
                m_review = result;
                if (result.value("descriptor", Json(nullptr)).is_object())
                {
                    m_chart->SetFrequencyUnit(StudioFrequency::ForDescriptor(result.at("descriptor")).unit);
                }
                m_chart->SetPage(result.value("page", Json(nullptr)), Display("기존 완료 계산"));
                m_details->ChangeValue(Display(Json{{"자료 조건", result.value("descriptor", Json(nullptr))},
                                                    {"진단", result.value("issues", Json::array())}}
                                                   .dump(2)));
                SetStatus(result.value("can_apply", false)
                              ? "기존 결과의 등록 후보입니다. 물리 모델과 실측 검증 상태는 그대로 유지됩니다."
                              : "자료를 등록할 수 없습니다. 진단을 확인하세요.");
                UpdateActions();
            });
}

void NetworkSolverDialog::Apply()
{
    if (!m_apply->IsEnabled())
    {
        return;
    }
    Request("network.apply",
            {{"expected_revision", m_revision},
             {"operation", "solver"},
             {"parameters", Parameters()},
             {"command_id", Uuid()},
             {"review_hash", m_review.at("review_hash")}},
            true,
            [this](const Json& result)
            {
                AcceptMutation(result);
                m_dirty = false;
                m_review = nullptr;
                SetStatus("자료를 등록했습니다. 프로젝트 저장으로 현재 개정을 보존하세요.");
                CloseDialog(true);
            });
}

NetworkDiagnosticsDialog::NetworkDiagnosticsDialog(wxWindow* parent, const Json& context, const Json& selection,
                                                   DialogGateway gateway)
    : ProjectSetupDialog(parent, "전체 계산 진단", context, std::move(gateway)),
      m_dataset(selection.at("entry").at("id"))
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_details =
        new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
    layout->Add(m_details, 1, wxEXPAND | wxALL, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, Display("봉인된 진단을 읽습니다."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 32개"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 32개"));
    actions->Add(m_previous, 0, wxALL, FromDIP(8));
    actions->Add(m_next, 0, wxALL, FromDIP(8));
    actions->AddStretchSpacer();
    actions->Add(new wxButton(this, wxID_CANCEL, Display("닫기")), 0, wxALL, FromDIP(8));
    layout->Add(actions, 0, wxEXPAND);
    SetSizer(layout);
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         Read(std::max(0, m_offset - 32));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     Read(m_nextOffset);
                 });
    UpdateActions();
    CallAfter(
        [this]()
        {
            Read(0);
        });
}

void NetworkDiagnosticsDialog::UpdateActions()
{
    m_previous->Enable(Editable() && m_offset > 0);
    m_next->Enable(Editable() && m_nextOffset >= 0);
}

void NetworkDiagnosticsDialog::Read(int offset)
{
    if (offset < 0)
    {
        return;
    }
    Request("network.diagnostics",
            {{"expected_revision", m_revision}, {"dataset_id", m_dataset}, {"offset", offset}, {"limit", 32}}, false,
            [this](const Json& result)
            {
                m_offset = result.at("offset");
                m_nextOffset = result.at("next_offset").is_null() ? -1 : result.at("next_offset").get<int>();
                m_details->ChangeValue(Display(result.at("diagnostics").dump(2)));
                const auto count = result.at("diagnostics").size();
                SetStatus("진단 " + std::to_string(count == 0 ? 0 : m_offset + 1) + "-" +
                          std::to_string(m_offset + count) + " (전체 " + result.at("total").dump() +
                          "개). 전체 진단은 원본 파일에 보존됩니다.");
                UpdateActions();
            });
}
