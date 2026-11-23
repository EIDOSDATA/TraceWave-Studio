/** @file @brief 고정 좌표계의 표면층과 설치 환경을 wxWidgets에서 편집한다. */
#include "studio_internal.h"
#include "physical_setup_dialog.h"
#include "studio_theme.h"

#include <array>
#include <wx/base64.h>
#include <wx/file.h>
#include <wx/filename.h>
#include <wx/scrolwin.h>

namespace
{
constexpr std::array<const char*, 5> Sections = {"stack", "surface", "activation", "scenario", "part"};

std::string SelectionValue(const wxChoice& choice)
{
    const int index = choice.GetSelection();
    if (index < 0)
    {
        return {};
    }
    return Utf8(static_cast<wxStringClientData*>(choice.GetClientObject(index))->GetData());
}

void AddChoice(wxChoice& choice, const std::string& label, const std::string& value)
{
    choice.Append(Display(label), new wxStringClientData(Display(value)));
}

void SelectValue(wxChoice& choice, const std::string& value)
{
    for (unsigned index = 0; index < choice.GetCount(); ++index)
    {
        const auto* entry = static_cast<wxStringClientData*>(choice.GetClientObject(index));
        if (Utf8(entry->GetData()) == value)
        {
            choice.SetSelection(static_cast<int>(index));
            return;
        }
    }
    choice.SetSelection(wxNOT_FOUND);
}
}

Json PhysicalSetupDialog::InitialSelection()
{
    return {{"section", Sections.front()}, {"record_id", nullptr}};
}

PhysicalSetupDialog::PhysicalSetupDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "PCB / 적층과 외부 환경", context, std::move(gateway))
{
    SetName("physical.setup.dialog");
    const int pad = FromDIP(StudioTheme::PanelPadding);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* select = new wxBoxSizer(wxHORIZONTAL);
    m_section = new wxChoice(this, wxID_ANY);
    m_section->SetName("physical.section");
    for (const auto* label : {"기본 적층 / 명목 두께", "표면층 / 개구", "활성 시나리오", "설치 시나리오", "외부 물체"})
    {
        m_section->Append(Display(label));
    }
    m_record = new wxChoice(this, wxID_ANY);
    m_record->SetName("physical.record");
    m_browse = new wxButton(this, wxID_ANY, Display("STEP 읽기 미리보기..."));
    select->Add(m_section, 0, wxRIGHT, pad);
    select->Add(m_record, 1, wxRIGHT, pad);
    m_storedStep = new wxButton(this, wxID_ANY, Display("저장된 STEP 면 보기"));
    select->Add(m_storedStep, 0, wxRIGHT, pad);
    select->Add(m_browse);
    layout->Add(select, 0, wxEXPAND | wxALL, pad);

    auto* content = new wxBoxSizer(wxHORIZONTAL);
    auto* summary = new wxBoxSizer(wxVERTICAL);
    m_sectionView = new wxPanel(this, wxID_ANY);
    m_sectionView->SetMinSize(wxSize(-1, FromDIP(86)));
    m_sectionView->Bind(wxEVT_PAINT, [this](wxPaintEvent&) { DrawSection(); });
    summary->Add(m_sectionView, 0, wxEXPAND | wxBOTTOM, pad);
    m_stack = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    m_stack->SetName("physical.stack");
    StudioTheme::Table(*m_stack);
    const std::array<const char*, 4> columns = {"층", "하부 z (mm)", "상부 z (mm)", "두께 (mm)"};
    for (std::size_t index = 0; index < columns.size(); ++index)
    {
        m_stack->AppendColumn(Display(columns[index]), wxLIST_FORMAT_LEFT, FromDIP(index == 0 ? 138 : 94));
    }
    summary->Add(m_stack, 1, wxEXPAND | wxBOTTOM, pad);
    m_review = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
    m_review->SetName("physical.review");
    summary->Add(m_review, 1, wxEXPAND);
    content->Add(summary, 1, wxEXPAND | wxRIGHT, pad);
    m_form = new wxScrolledWindow(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxBORDER_THEME);
    m_form->SetScrollRate(0, FromDIP(12));
    m_form->SetSizer(new wxBoxSizer(wxVERTICAL));
    content->Add(m_form, 1, wxEXPAND);
    layout->Add(content, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);

    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, pad);
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->Add(new wxStaticText(this, wxID_ANY, Display("변경 사유 / 출처")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, pad);
    m_reason = new wxTextCtrl(this, wxID_ANY);
    m_reason->SetName("physical.reason");
    m_reason->SetMaxLength(512);
    actions->Add(m_reason, 1, wxEXPAND | wxRIGHT, pad);
    m_apply = new wxButton(this, wxID_ANY, Display("적용"));
    m_apply->SetName("physical.apply");
    m_remove = new wxButton(this, wxID_ANY, Display("제거"));
    for (auto* button : {m_apply, m_remove, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(6));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    SetSizer(layout);
    m_section->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { Switch(); });
    m_record->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { Switch(); });
    m_reason->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { UpdateActions(); });
    m_apply->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Apply(false); });
    m_remove->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Apply(true); });
    m_browse->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { BrowseStep(); });
    m_storedStep->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Request("physical.step.preview", {{"expected_revision", m_revision}, {"record_id", m_context.at("record_id")}},
                false, [this](const Json& result)
                {
                    m_stepReview = result;
                    RenderReview();
                    SetStatus("저장된 원본 STEP의 조립 경로와 메이트 면을 표시했습니다.");
                });
    });
    Render(context);
}

void PhysicalSetupDialog::SelectCurrent()
{
    for (std::size_t index = 0; index < Sections.size(); ++index)
    {
        if (m_context.at("section") == Sections[index])
        {
            m_section->SetSelection(static_cast<int>(index));
        }
    }
    SelectValue(*m_record, m_context.at("record_id").is_null() ? "" : m_context.at("record_id").get<std::string>());
}

void PhysicalSetupDialog::Render(const Json& context)
{
    m_refreshing = false;
    m_context = context;
    m_stepReview = nullptr;
    m_record->Clear();
    AddChoice(*m_record, "새 항목", "");
    const std::string section = context.at("section");
    if (context.at("records").contains(section))
    {
        for (const auto& row : context.at("records").at(section))
        {
            AddChoice(*m_record, row.at("name"), row.at("id"));
        }
    }
    SelectCurrent();
    m_reason->ChangeValue(wxEmptyString);
    RenderFields();
    RenderReview();
    SetStatus("빈 수치는 미정입니다. 제작 및 측정 조건은 별도 자료로 확인합니다.");
    UpdateActions();
}

void PhysicalSetupDialog::Load(const std::string& section, const Json& identity)
{
    Request("physical.setup.get", {{"expected_revision", m_revision}, {"section", section}, {"record_id", identity}}, false,
            [this](const Json& context) { Render(context); });
}

void PhysicalSetupDialog::Switch()
{
    const std::string section = Sections.at(static_cast<std::size_t>(m_section->GetSelection()));
    const std::string identity = section == m_context.at("section") ? SelectionValue(*m_record) : "";
    SelectCurrent();
    if (ConfirmDiscard())
    {
        Load(section, identity.empty() ? Json(nullptr) : Json(identity));
    }
}

void PhysicalSetupDialog::BrowseStep()
{
    wxFileDialog chooser(this, Display("외부 STEP 파일"), wxEmptyString, wxEmptyString,
                         Display("STEP 파일 (*.step;*.stp)|*.step;*.stp"), wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (chooser.ShowModal() == wxID_OK)
    {
        ReviewStep(chooser.GetPath());
    }
}

void PhysicalSetupDialog::ReviewStep(const wxString& path)
{
    constexpr std::size_t Limit = 48U * 1024U;
    wxFile file(path, wxFile::read);
    const auto size = file.IsOpened() ? file.Length() : wxInvalidOffset;
    if (size <= 0 || size > static_cast<wxFileOffset>(Limit))
    {
        SetStatus("읽을 수 있는 STEP 파일을 선택하십시오. 원본 상한은 48 KiB입니다.");
        return;
    }
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    if (file.Read(bytes.data(), bytes.size()) != size || file.Length() != size)
    {
        SetStatus("STEP을 읽는 도중 파일이 바뀌었습니다. 다시 선택하십시오.");
        return;
    }
    const std::string encoded = Utf8(wxBase64Encode(bytes.data(), bytes.size()));
    Json chunks = Json::array();
    for (std::size_t offset = 0; offset < encoded.size(); offset += 4096)
    {
        chunks.push_back(encoded.substr(offset, 4096));
    }
    m_stepReview = nullptr;
    RenderReview();
    SetStatus("별도 CAD 작업에서 STEP 원본, 단위와 고체를 확인하는 중입니다.");
    Request("physical.step.preview", {{"expected_revision", m_revision}, {"name", Utf8(wxFileName(path).GetFullName())},
                                      {"chunks", chunks}}, false,
            [this](const Json& result)
            {
                m_stepReview = result;
                SelectValue(*static_cast<wxChoice*>(m_inputs.at("kind")), "step");
                RenderReview();
                SetStatus("STEP 미리보기 완료. 좌표와 포함 범위를 확인한 뒤 적용하십시오.");
            });
}

void PhysicalSetupDialog::Apply(bool remove)
{
    if (!Editable() || m_pending || m_refreshing || m_reason->GetValue().Trim().Trim(false).empty())
    {
        return;
    }
    const std::string section = m_context.at("section");
    const Json input{{"expected_revision", m_revision}, {"command_id", Uuid()}, {"section", section},
                     {"record_id", m_context.at("record_id")}, {"operation", remove ? "remove" : "set"},
                     {"changes", remove ? Json::object() : Changes()}, {"reason", Utf8(m_reason->GetValue())},
                     {"step_token", remove || m_stepReview.is_null() || Value("kind") != "step" ? Json(nullptr)
                                                                                              : m_stepReview.at("preview_token")}};
    Request("physical.setup.apply", input, true,
            [this, section](const Json& result)
            {
                AcceptMutation(result);
                m_stepReview = nullptr;
                m_refreshing = true;
                m_reason->ChangeValue(wxEmptyString);
                Load(section, result.at("record_id"));
                SetStatus("적용했습니다. 프로젝트 저장으로 현재 개정을 보존할 수 있습니다.");
            });
}

void PhysicalSetupDialog::ShowRequestFailure(const Json& error)
{
    if (m_refreshing)
    {
        m_needsReload = true;
        SetStatus("변경은 적용됐습니다. 창을 닫고 현재 개정에서 다시 여세요.");
        return;
    }
    SetStatus(DiagnosticMessage(error));
}
