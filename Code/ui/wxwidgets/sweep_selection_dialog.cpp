/** @file @brief 후보 형상과 출처를 검토한 뒤 별도 사본 생성과 열기를 분리한다. */
#include "sweep_selection_dialog.h"
#include "sweep_selection_model.h"
#include "design_canvas.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/wrapsizer.h>
#include <wx/weakref.h>

namespace
{
/** @brief 검토 전 빈 화면도 캔버스의 필수 표시 DTO 형식을 유지한다. */
Json EmptyScene()
{
    return {{"board", nullptr}, {"layers", Json::array()}, {"shapes", Json::array()}, {"omissions", Json::array()}};
}
}

SweepSelectionDialog::SweepSelectionDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                           std::shared_ptr<SweepSelectionRecovery> recovery)
    : ProjectSetupDialog(parent, "새 작업 사본으로 채택", context, gateway), m_context(context),
      m_recoveryGateway(std::move(gateway)), m_recovery(std::move(recovery))
{
    SetName("sweep.selection.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("후보 검토 / 새 작업 사본"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    auto* notice = new wxStaticText(
        this, wxID_ANY,
        Display("후보를 선택해도 현재 설계는 바뀌지 않습니다. 이름과 저장 위치까지 검토한 뒤 별도 사본으로 만듭니다."));
    StudioTheme::BindSecondary(*notice);
    layout->Add(notice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    m_tabs = new StudioNotebook(this);
    auto* reviewPage =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    reviewPage->SetScrollRate(0, FromDIP(16));
    auto* reviewLayout = new wxBoxSizer(wxVERTICAL);
    m_sceneChoice = new wxChoice(reviewPage, wxID_ANY);
    m_sceneChoice->Append(Display("선택 후보 형상"));
    m_sceneChoice->Append(Display("연구 기준 형상"));
    m_sceneChoice->SetSelection(0);
    reviewLayout->Add(m_sceneChoice, 0, wxALL, FromDIP(8));
    m_canvas = new DesignCanvas(reviewPage);
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetMinSize(FromDIP(wxSize(320, 180)));
    reviewLayout->Add(m_canvas, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_changes = new wxListCtrl(reviewPage, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 130)),
                               wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_changes->SetName("sweep.selection.changes");
    m_changes->SetMinSize(FromDIP(wxSize(-1, 110)));
    StudioTheme::Table(*m_changes);
    for (const auto& item : std::vector<std::pair<std::string, int>>{
             {"선택 치수", 250}, {"연구 기준", 220}, {"선택 후보", 220}, {"단위", 100}})
    {
        m_changes->AppendColumn(Display(item.first), wxLIST_FORMAT_LEFT, FromDIP(item.second));
    }
    reviewLayout->Add(m_changes, 0, wxEXPAND | wxALL, FromDIP(8));
    m_issues = new wxTextCtrl(reviewPage, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 68)),
                              wxTE_MULTILINE | wxTE_READONLY);
    reviewLayout->Add(m_issues, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    reviewPage->SetSizer(reviewLayout);
    reviewPage->Bind(wxEVT_SIZE,
                     [reviewPage](wxSizeEvent& event)
                     {
                         reviewPage->Layout();
                         reviewPage->FitInside();
                         event.Skip();
                     });
    m_tabs->AddPage(reviewPage, Display("후보 검토"));

    auto* conditionPage =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    conditionPage->SetScrollRate(0, FromDIP(16));
    auto* conditionsLayout = new wxBoxSizer(wxVERTICAL);
    m_conditions = new wxTextCtrl(conditionPage, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 360)),
                                  wxTE_MULTILINE | wxTE_READONLY);
    m_conditions->SetName("sweep.selection.conditions");
    conditionsLayout->Add(m_conditions, 1, wxEXPAND | wxALL, FromDIP(12));
    m_advanced = new wxCollapsiblePane(conditionPage, wxID_ANY, Display("고급 상세 / 원문과 봉인 식별"));
    auto* advancedLayout = new wxBoxSizer(wxVERTICAL);
    m_source = new wxTextCtrl(m_advanced->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition,
                              FromDIP(wxSize(-1, 190)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    advancedLayout->Add(m_source, 1, wxEXPAND | wxALL, FromDIP(8));
    m_advanced->GetPane()->SetSizer(advancedLayout);
    m_advanced->Collapse();
    conditionsLayout->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(12));
    conditionPage->SetSizer(conditionsLayout);
    m_advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                     [conditionPage](wxCollapsiblePaneEvent&)
                     {
                         conditionPage->Layout();
                         conditionPage->FitInside();
                     });
    m_tabs->AddPage(conditionPage, Display("출처와 조건"));

    auto* copyPage =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    copyPage->SetScrollRate(0, FromDIP(16));
    auto* copyLayout = new wxBoxSizer(wxVERTICAL);
    const auto field = [this, copyPage, copyLayout](const std::string& label, const std::string& name,
                                                    const std::string& value, bool multiline)
    {
        copyLayout->Add(new wxStaticText(copyPage, wxID_ANY, Display(label)), 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
        auto* input =
            new wxTextCtrl(copyPage, wxID_ANY, Display(value), wxDefaultPosition,
                           multiline ? FromDIP(wxSize(-1, 90)) : wxDefaultSize, multiline ? wxTE_MULTILINE : 0);
        input->SetName(Display(name));
        copyLayout->Add(input, 0, wxEXPAND | wxALL, FromDIP(12));
        return input;
    };
    const auto defaults = context.value("defaults", Json::object());
    m_name = field("새 사본 이름", "sweep.selection.name", defaults.value("name", ""), false);
    m_path = field("새 저장 위치 (작업공간 기준 경로)", "sweep.selection.path", defaults.value("path", ""), false);
    m_reason = field("선택 사유 / 이력에 보존", "sweep.selection.reason", defaults.value("reason", ""), true);
    m_copySummary = new wxTextCtrl(copyPage, wxID_ANY, Display(SweepSelectionUi::CopySummary(Json::object())),
                                   wxDefaultPosition, FromDIP(wxSize(-1, 170)), wxTE_MULTILINE | wxTE_READONLY);
    copyLayout->Add(m_copySummary, 1, wxEXPAND | wxALL, FromDIP(12));
    copyPage->SetSizer(copyLayout);
    m_tabs->AddPage(copyPage, Display("새 작업 사본"));
    m_tabs->SetSelection(context.value("eligibility", Json::object()).value("can_select", false) ? 2 : 0);
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(
        this, wxID_ANY,
        Display("후보와 새 저장 위치를 검토하세요. 계산 완료와 수렴/실측 검증은 서로 다른 상태입니다."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_preview = new wxButton(this, wxID_ANY, Display("후보 / 저장 위치 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 새 사본 생성"));
    m_recover = new wxButton(this, wxID_ANY, Display("생성 결과 다시 확인"));
    m_open = new wxButton(this, wxID_ANY, Display("새 사본 열기"));
    m_preview->SetName("sweep.selection.preview");
    m_apply->SetName("sweep.selection.apply");
    m_recover->SetName("sweep.selection.recover");
    m_open->SetName("sweep.selection.open");
    for (auto* button : {close, m_preview, m_apply, m_recover, m_open})
    {
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    for (auto* input : {m_name, m_path, m_reason})
    {
        input->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
    m_sceneChoice->Bind(wxEVT_CHOICE,
                        [this](wxCommandEvent&)
                        {
                            ShowScene();
                        });
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
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Recover();
                    });
    m_open->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (m_applied.is_object() && !m_pending && !m_recovering)
                     {
                         m_openRequested = true;
                         CloseDialog();
                     }
                 });
    m_conditions->ChangeValue(Display(SweepSelectionUi::Conditions(context)));
    m_source->ChangeValue(Display(context.dump(2)));
    m_issues->ChangeValue(
        Display(SweepSelectionUi::Issues(context.value("eligibility", Json::object()).value("issues", Json::array()))));
    if (m_recovery && m_recovery->uncertain)
    {
        m_disconnected = true;
        if (m_recovery->input.is_object())
        {
            m_name->ChangeValue(Display(m_recovery->input.value("name", "")));
            m_path->ChangeValue(Display(m_recovery->input.value("path", "")));
            m_reason->ChangeValue(Display(m_recovery->input.value("reason", "")));
        }
        SetStatus("이전 생성 요청의 결과가 미확정입니다. 새 사본을 다시 만들지 않고 보존된 요청 영수증만 조회합니다.");
    }
    Layout();
    UpdateActions();
}

Json SweepSelectionDialog::Input() const
{
    return Json{{"expected_revision", m_revision},          {"study_id", m_context.at("study_id")},
                {"index", m_context.at("index")},           {"definition_hash", m_context.at("definition_hash")},
                {"source_pin", m_context.at("source_pin")}, {"name", Utf8(m_name->GetValue())},
                {"path", Utf8(m_path->GetValue())},         {"reason", Utf8(m_reason->GetValue())}};
}

void SweepSelectionDialog::Changed()
{
    if (m_mutating || m_recovering || m_applied.is_object())
    {
        return;
    }
    InvalidateRead();
    m_dirty = true;
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_changes->DeleteAllItems();
    m_canvas->SetScene(EmptyScene());
    SetStatus("입력이 바뀌었습니다. 후보와 저장 위치를 다시 검토하세요.");
    UpdateActions();
}

void SweepSelectionDialog::Preview()
{
    if (!Editable() || m_pending || m_applied.is_object())
    {
        return;
    }
    const Json input = Input();
    m_review = nullptr;
    m_reviewInput = nullptr;
    Request(
        "sweep.selection.preview", input, false,
        [this, input](const Json& result)
        {
            if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision ||
                result.at("study_id") != m_context.at("study_id") || result.at("index") != m_context.at("index") ||
                (result.value("can_apply", false) &&
                 result.value("source_pin", Json(nullptr)) != m_context.at("source_pin")))
            {
                throw std::runtime_error("선택한 후보와 검토 응답의 원본 식별이 다릅니다.");
            }
            m_review = result;
            m_reviewInput = input;
            Render(result);
            SetStatus(
                result.value("can_apply", false)
                    ? "선택 치수, 원본 조건과 새 사본 위치를 검토했습니다. 새 사본 생성은 원본 설계를 바꾸지 않습니다."
                    : "이 후보를 채택할 수 없습니다. 안내와 조건을 확인하세요.");
        });
}

void SweepSelectionDialog::Render(const Json& review)
{
    m_changes->DeleteAllItems();
    for (const auto& change : review.value("changes", Json::array()))
    {
        const long row = m_changes->InsertItem(m_changes->GetItemCount(), Display(change.value("label", "치수")));
        m_changes->SetItem(row, 1, Display(change.value("before_display", "미정")));
        m_changes->SetItem(row, 2, Display(change.value("after_display", "미정")));
        m_changes->SetItem(row, 3, Display(change.value("unit", "")));
    }
    Json display = m_context;
    display.update(review);
    m_conditions->ChangeValue(Display(SweepSelectionUi::Conditions(display)));
    m_issues->ChangeValue(Display(SweepSelectionUi::Issues(review.value("issues", Json::array()))));
    if (review.value("copy_summary", Json::object()).value("source_revision_matches_current", Json(nullptr)) == false)
    {
        m_issues->ChangeValue(Display(
            "주의: 연구 당시 기준에서 사본을 만듭니다. 현재 원본에 추가한 후속 편집은 사본에 포함하지 않습니다.\n" +
            SweepSelectionUi::Issues(review.value("issues", Json::array()))));
    }
    m_copySummary->ChangeValue(Display(SweepSelectionUi::CopySummary(review)));
    m_source->ChangeValue(Display(review.dump(2)));
    m_tabs->SetSelection(0);
    ShowScene();
}

void SweepSelectionDialog::ShowScene()
{
    const Json scene =
        m_review.is_object()
            ? m_review.value(m_sceneChoice->GetSelection() == 1 ? "before_scene" : "scene", Json(nullptr))
            : Json(nullptr);
    m_canvas->SetScene(scene.is_object() ? scene : EmptyScene());
    Layout();
    m_canvas->FitView();
}

void SweepSelectionDialog::Apply()
{
    if (!Editable() || m_pending || m_applied.is_object() || !m_review.is_object() ||
        !m_review.value("can_apply", false) || Input() != m_reviewInput)
    {
        return;
    }
    Json input = m_reviewInput;
    input["review_hash"] = m_review.at("review_hash");
    input["command_id"] = Uuid();
    Request("sweep.selection.apply", input, true,
            [this](const Json& result)
            {
                AcceptCopy(result);
            });
}

void SweepSelectionDialog::AcceptCopy(const Json& result)
{
    if (!SweepSelectionUi::MatchesCopy(result, m_context))
    {
        throw std::runtime_error("새 사본의 원본 프로젝트 / 후보 / 봉인 식별이 검토 내용과 다릅니다.");
    }
    m_applied = result;
    m_dirty = false;
    m_disconnected = false;
    m_needsReload = false;
    SetStatus("새 작업 사본을 생성했습니다. 현재 원본은 그대로입니다. '새 사본 열기'로 명시적으로 이동할 수 있습니다.");
    m_copySummary->ChangeValue(Display(SweepSelectionUi::CopySummary(m_review.is_object() ? m_review : Json::object()) +
                                       "\n\n생성 위치\n" + result.at("path").get<std::string>()));
    UpdateActions();
}

void SweepSelectionDialog::Recover()
{
    if (m_closed || m_pending || m_recovering || !m_recovery || !m_recovery->uncertain)
    {
        return;
    }
    m_recovering = true;
    UpdateActions();
    wxWeakRef<SweepSelectionDialog> weak(this);
    try
    {
        m_recoveryGateway(
            "sweep.selection.receipt",
            {{"request_key", m_recovery->requestKey}, {"request_key_epoch", m_recovery->epoch}}, false,
            [weak](const Json& result)
            {
                if (!weak || weak->m_closed)
                {
                    return;
                }
                weak->m_recovering = false;
                try
                {
                    if (result.value("authoritative", false) && result.value("status", "") == "found" &&
                        result.value("response", Json(nullptr)).is_object())
                    {
                        weak->AcceptCopy(result.at("response"));
                    }
                    else
                    {
                        weak->SetStatus("생성 결과를 아직 확정할 수 없습니다. 중복 생성은 잠긴 상태로 유지합니다.\n" +
                                        result.value("reason", "보존 요청의 결과를 다시 확인하세요."));
                    }
                }
                catch (const std::exception& error)
                {
                    weak->SetStatus(std::string("생성 결과 검증 실패 / 중복 생성 잠금 유지\n") + error.what());
                }
                weak->UpdateActions();
            },
            [weak](const Json& error)
            {
                if (!weak || weak->m_closed)
                {
                    return;
                }
                weak->m_recovering = false;
                weak->SetStatus("생성 결과 조회 실패 / 중복 생성 잠금 유지\n" + DiagnosticMessage(error));
                weak->UpdateActions();
            });
    }
    catch (const std::exception& error)
    {
        m_recovering = false;
        SetStatus(std::string("생성 결과 조회를 전송하지 못했습니다. 중복 생성 잠금을 유지합니다.\n") + error.what());
        UpdateActions();
    }
}

bool SweepSelectionDialog::HasDraft() const
{
    return m_dirty && !m_disconnected && !m_applied.is_object();
}

bool SweepSelectionDialog::OpenRequested() const
{
    return m_openRequested && m_applied.is_object();
}

void SweepSelectionDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool uncertain = m_recovery && m_recovery->uncertain;
    const bool editable = Editable() && !m_pending && !m_recovering && !m_applied.is_object() && !uncertain &&
                          m_context.value("eligibility", Json::object()).value("can_select", false);
    for (auto* field : {m_name, m_path, m_reason})
    {
        field->Enable(editable);
    }
    m_preview->Enable(editable && m_context.value("eligibility", Json::object()).value("can_select", false));
    m_apply->Enable(editable && m_review.is_object() && m_review.value("can_apply", false));
    m_recover->Enable(uncertain && !m_pending && !m_mutating && !m_recovering && !m_closed);
    m_recover->Show(uncertain);
    m_open->Enable(m_applied.is_object() && !m_pending && !m_recovering);
    Layout();
}

void SweepSelectionDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_canvas->SetScene(EmptyScene());
    m_changes->DeleteAllItems();
    ProjectSetupDialog::ShowRequestFailure(error);
}
