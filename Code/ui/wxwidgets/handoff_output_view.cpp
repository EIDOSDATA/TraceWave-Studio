/** @file @brief 52번 시안의 근거 표와 검토/저장 동작을 native 컨트롤로 구성한다. */
#include "handoff_output_view.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>
#include <map>

namespace
{
constexpr int PageSize = 12;

wxButton* Button(wxWindow* parent, wxSizer& layout, const char* label)
{
    auto* button = new wxButton(parent, wxID_ANY, Display(label));
    StudioTheme::Button(*button);
    layout.Add(button, 0, wxALL, parent->FromDIP(4));
    return button;
}

Json Selection(const Json& row)
{
    return {{"kind", row.at("kind")}, {"id", row.at("id")}};
}

std::string Kind(const std::string& value)
{
    static const std::map<std::string, std::string> labels{
        {"snapshot", "고정 설계"},      {"material", "재료"},
        {"target", "설계 목표"},        {"network", "복소 자료"},
        {"assessment", "목표 평가"},    {"measurement", "측정 기록"},
        {"alignment", "정렬 기록"},     {"comparison", "비교 기록"},
        {"solver_result", "해석 결과"}, {"verification_report", "검증 보고서"},
        {"output", "출력 기록"},
    };
    const auto found = labels.find(value);
    return found == labels.end() ? value : found->second;
}

std::string CopyState(const std::string& value)
{
    static const std::map<std::string, std::string> labels{
        {"included", "파일 포함"},
        {"external_storage_reference_only", "외부 저장 / 참조만"},
        {"registered_reference_only", "등록 근거 / 참조만"},
        {"no_file_record", "기록만"},
    };
    const auto found = labels.find(value);
    return found == labels.end() ? value : found->second;
}

/** @brief 과거 명령 문자열과 고정 참조는 보존하고 화면에서는 출력의 역할을 읽기 쉽게 표시한다. */
std::string EvidenceName(const Json& row)
{
    const auto name = row.at("name").get<std::string>();
    if (row.at("kind") != "output")
    {
        return name;
    }
    if (name == "geometry.build")
    {
        return "3D 표시 형상";
    }
    const auto format = row.value("detail", Json::object()).value("format", Json(nullptr));
    const std::string title = format == "pdf" ? "PDF 도면" : format == "svg" ? "SVG 도면" :
        (format == "step" ? "STEP 교환" : format == "gerber_job" ? "Gerber Job / 드릴" : "보존 출력");
    return title + (name == "export.verify" ? " 검수" : " 생성");
}
}

HandoffOutputView::HandoffOutputView(wxWindow* parent) : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("보고서와 인계 묶음"));
    StudioTheme::Title(*title);
    auto* heading = new wxBoxSizer(wxHORIZONTAL);
    heading->Add(title, 1, wxALIGN_CENTER_VERTICAL);
    m_format = new wxChoice(this, wxID_ANY);
    m_format->SetName(Display("인계 묶음 형식"));
    m_format->Append(Display("읽기 전용 보고서와 인계"));
    m_format->Append(Display("편집 복원용 프로젝트 묶음"));
    m_format->SetSelection(0);
    heading->Add(m_format, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, FromDIP(8));
    layout->Add(heading, 0, wxEXPAND | wxALL, FromDIP(12));

    m_list = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 150)),
                            wxLC_REPORT | wxLC_SINGLE_SEL | wxBORDER_SIMPLE);
    StudioTheme::Table(*m_list);
    m_list->SetName(Display("인계 근거 목록"));
    m_list->AppendColumn(Display("항목"), wxLIST_FORMAT_LEFT, FromDIP(135));
    m_list->AppendColumn(Display("자료"), wxLIST_FORMAT_LEFT, FromDIP(285));
    m_list->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(210));
    layout->Add(m_list, 1, wxEXPAND | wxALL, FromDIP(12));

    auto* selection = new wxWrapSizer(wxHORIZONTAL);
    m_previous = Button(this, *selection, "이전 근거");
    m_next = Button(this, *selection, "다음 근거");
    m_include = Button(this, *selection, "선택 파일 포함");
    m_remove = Button(this, *selection, "포함 해제");
    m_rights = new wxCheckBox(this, wxID_ANY, Display("선택 파일 공유 권한 확인"));
    selection->Add(m_rights, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    layout->Add(selection, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));

    m_summary = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_summary, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
    auto* review = new wxWrapSizer(wxHORIZONTAL);
    m_preview = Button(this, *review, "인계 범위 검토");
    m_report = Button(this, *review, "보고서 미리보기");
    m_files = Button(this, *review, "파일 목록 검토");
    m_build = Button(this, *review, "인계 묶음 생성");
    layout->Add(review, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));

    auto* history = new wxWrapSizer(wxHORIZONTAL);
    history->Add(new wxStaticText(this, wxID_ANY, Display("발행 기록")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
                 FromDIP(4));
    m_history = new wxChoice(this, wxID_ANY);
    m_history->SetName(Display("발행 기록"));
    m_history->SetMinSize(FromDIP(wxSize(265, -1)));
    history->Add(m_history, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_save = Button(this, *history, "ZIP 사본 저장");
    layout->Add(history, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);

    m_format->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       FormatChanged();
                   });
    m_list->Bind(wxEVT_LIST_ITEM_SELECTED,
                 [this](wxListEvent&)
                 {
                     UpdateActions();
                 });
    m_list->Bind(wxEVT_LIST_ITEM_DESELECTED,
                 [this](wxListEvent&)
                 {
                     UpdateActions();
                 });
    m_list->Bind(wxEVT_SIZE,
                 [this](wxSizeEvent& event)
                 {
                     const int width = m_list->GetClientSize().x;
                     if (width >= FromDIP(440))
                     {
                         m_list->SetColumnWidth(0, width * 22 / 100);
                         m_list->SetColumnWidth(1, width * 48 / 100);
                         m_list->SetColumnWidth(2, width * 29 / 100);
                     }
                     event.Skip();
                 });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         onPage(std::max(0, m_page.at("offset").get<int>() - PageSize));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     onPage(m_page.at("next_offset").get<int>());
                 });
    m_include->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Select(true);
                    });
    m_remove->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Select(false);
                   });
    m_rights->Bind(wxEVT_CHECKBOX,
                   [this](wxCommandEvent&)
                   {
                       SetReview(nullptr);
                   });
    m_history->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        UpdateActions();
                    });
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        onPreview();
                    });
    m_build->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      onBuild();
                  });
    m_report->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       ShowDetails(false);
                   });
    m_files->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      ShowDetails(true);
                  });
    m_save->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     onSave();
                 });
    ResetEvidence();
}

bool HandoffOutputView::ArchiveMode() const
{
    return m_archiveSupported && m_format->GetSelection() == 1;
}

void HandoffOutputView::SetArchiveSupported(bool supported)
{
    if (m_archiveSupported == supported)
    {
        return;
    }
    m_archiveSupported = supported;
    if (!supported && m_format->GetSelection() == 1)
    {
        m_format->SetSelection(0);
        FormatChanged();
    }
    UpdateActions();
}

void HandoffOutputView::SetArchiveMode(bool archive)
{
    const int target = archive && m_archiveSupported ? 1 : 0;
    if (m_format->GetSelection() != target)
    {
        m_format->SetSelection(target);
        FormatChanged();
    }
}

void HandoffOutputView::FormatChanged()
{
    const bool archive = ArchiveMode();
    m_previous->Show(!archive);
    m_next->Show(!archive);
    m_include->Show(!archive);
    m_remove->Show(!archive);
    m_rights->SetLabel(Display(archive ? "공유 권한을 확인한 등록 원문 포함" : "선택 파일 공유 권한 확인"));
    m_report->SetLabel(Display(archive ? "포함 범위와 누락 검토" : "보고서 미리보기"));
    m_review = nullptr;
    ResetEvidence();
    SetCatalog(nullptr);
    Layout();
    if (onModeChanged)
    {
        onModeChanged();
    }
}

void HandoffOutputView::ShowArchiveRows()
{
    const auto add = [this](const char* item, const std::string& description, const char* state)
    {
        const auto index = m_list->InsertItem(m_list->GetItemCount(), Display(item));
        m_list->SetItem(index, 1, Display(description));
        m_list->SetItem(index, 2, Display(state));
    };
    m_list->DeleteAllItems();
    const auto revision =
        m_review.is_object() ? m_review.at("revision_id").get<std::string>() : "검토 시 현재 개정 확인";
    add("설계와 저장본", revision, "보존");
    add("명령과 스냅샷", "선택한 프로젝트의 등록 이력", "보존");
    add("등록 원문", m_rights->GetValue() ? "공유 권한을 확인한 소유 자료" : "원래 참조 및 누락 기록",
        m_rights->GetValue() ? "포함 요청" : "참조만");
    add("작업 실행", "작업 대기열과 환경은 제외", "자동 실행 없음");
}

void HandoffOutputView::ResetEvidence()
{
    m_selected = Json::array();
    m_rights->SetValue(false);
    SetEvidence(nullptr);
    SetReview(nullptr);
}

void HandoffOutputView::SetEvidence(const Json& value)
{
    m_page = value;
    m_list->DeleteAllItems();
    if (ArchiveMode())
    {
        ShowArchiveRows();
    }
    else if (m_page.is_object())
    {
        for (const auto& row : m_page.at("items"))
        {
            const long index = m_list->InsertItem(m_list->GetItemCount(), Display(Kind(row.at("kind"))));
            m_list->SetItem(index, 1, Display(EvidenceName(row)));
            const auto selected = Selection(row);
            const bool included = std::find(m_selected.begin(), m_selected.end(), selected) != m_selected.end();
            const bool file =
                row.at("artifact").is_object() || !row.at("detail").value("artifacts", Json::array()).empty();
            m_list->SetItem(index, 2, Display(included ? "파일 포함 요청" : file ? "등록 근거" : "조건 / 기록"));
        }
    }
    UpdateActions();
}

void HandoffOutputView::Select(bool include)
{
    const long index = m_list->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (index < 0 || !m_page.is_object() || static_cast<std::size_t>(index) >= m_page.at("items").size())
    {
        return;
    }
    const auto selected = Selection(m_page.at("items").at(index));
    auto found = std::find(m_selected.begin(), m_selected.end(), selected);
    if (include && found == m_selected.end() && m_selected.size() < 64)
    {
        m_selected.push_back(selected);
    }
    if (!include && found != m_selected.end())
    {
        m_selected.erase(found);
    }
    if (m_selected.empty())
    {
        m_rights->SetValue(false);
    }
    auto page = m_page;
    SetEvidence(page);
    m_list->SetItemState(index, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
    SetReview(nullptr);
}

void HandoffOutputView::SetCatalog(const Json& value, const std::string& preferred)
{
    const auto current = SelectedPackage();
    const std::string keep = preferred.empty() && current.is_object() ? current.value("package_id", "") : preferred;
    m_packages = value.is_object() ? value.at("items") : Json::array();
    m_history->Clear();
    for (const auto& row : m_packages)
    {
        const auto index = m_history->Append(Display(row.at("file_name").get<std::string>() + " / " +
                                                     row.at("artifact").at("sha256").get<std::string>().substr(0, 8)));
        if (row.at("package_id") == keep)
        {
            m_history->SetSelection(index);
        }
    }
    UpdateActions();
}

void HandoffOutputView::SetReview(const Json& value)
{
    m_review = value;
    if (ArchiveMode())
    {
        ShowArchiveRows();
    }
    UpdateActions();
    if (onReviewChanged)
    {
        onReviewChanged();
    }
}

void HandoffOutputView::SetAvailable(bool available, bool snapshot)
{
    if (available != m_available || snapshot != m_snapshot)
    {
        m_available = available;
        m_snapshot = snapshot;
        UpdateActions();
    }
}

const Json& HandoffOutputView::Review() const
{
    return m_review;
}

Json HandoffOutputView::Input() const
{
    if (ArchiveMode())
    {
        return {{"include_sources", m_rights->GetValue()}};
    }
    return {{"records", m_selected},
            {"inclusion", m_selected.empty() ? "design_and_report" : "include_selected_files"},
            {"rights_confirmed", m_rights->GetValue()}};
}

Json HandoffOutputView::SelectedPackage() const
{
    const int index = m_history->GetSelection();
    return index >= 0 && static_cast<std::size_t>(index) < m_packages.size() ? m_packages.at(index) : Json(nullptr);
}

void HandoffOutputView::UpdateActions()
{
    const bool archive = ArchiveMode();
    const bool ready = m_available && (archive || (m_snapshot && m_page.is_object()));
    m_format->Enable(m_available && m_archiveSupported);
    const long index = m_list->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    bool file = false, included = false;
    if (!archive && ready && index >= 0 && static_cast<std::size_t>(index) < m_page.at("items").size())
    {
        const auto& row = m_page.at("items").at(index);
        const auto selected = Selection(row);
        included = std::find(m_selected.begin(), m_selected.end(), selected) != m_selected.end();
        file = row.at("kind") != "snapshot" &&
               (row.at("artifact").is_object() || !row.at("detail").value("artifacts", Json::array()).empty());
    }
    m_include->Enable(ready && file && !included && m_selected.size() < 64);
    m_remove->Enable(ready && included);
    m_rights->Enable(ready && (archive || !m_selected.empty()));
    m_previous->Enable(ready && !archive && m_page.value("offset", 0) > 0);
    m_next->Enable(ready && !archive && !m_page.at("next_offset").is_null());
    m_preview->Enable(ready && (archive || m_selected.empty() || m_rights->GetValue()));
    m_build->Enable(ready && m_review.is_object());
    m_report->Enable(m_review.is_object());
    m_files->Enable(m_review.is_object());
    m_history->Enable(m_available && !m_packages.empty());
    m_save->Enable(m_available && SelectedPackage().is_object());
    std::string info =
        m_snapshot ? "고정 설계와 보고서를 포함합니다. 파일 포함 선택 " + std::to_string(m_selected.size()) + " / 64"
                   : "위 목록에서 고정 입력을 선택하세요. 발행 기록은 따로 열 수 있습니다.";
    if (archive)
    {
        info = "현재 적용 개정과 저장 기준점으로 편집 복원용 ZIP을 만듭니다.";
        if (m_review.is_object())
        {
            info = "검토 완료 / 파일 " + std::to_string(m_review.at("file_count").get<int>()) + "개 / 제외 및 미확보 " +
                   std::to_string(m_review.at("missing_count").get<int>()) + "개 / " +
                   std::to_string(m_review.at("estimated_bytes").get<int>()) + " B";
        }
    }
    else if (m_review.is_object())
    {
        info = "검토 완료 / 보고서 근거 " + std::to_string(m_review.at("evidence_count").get<int>()) + "건 / " +
               std::to_string(m_review.at("estimated_bytes").get<int>()) + " B";
    }
    const auto label = Display(
        info + (archive ? "\n제작/실측 합격 미확립 / 편집 복원용" : "\n제작/실측 합격 미확립 / 읽기 전용 인계"));
    if (m_summary->GetLabel() != label)
    {
        m_summary->SetLabel(label);
        Layout();
    }
}

void HandoffOutputView::ShowDetails(bool files)
{
    if (!m_review.is_object())
    {
        return;
    }
    const bool archive = ArchiveMode();
    wxDialog dialog(this, wxID_ANY,
                    Display(files     ? "인계 파일 목록"
                            : archive ? "포함 범위와 누락"
                                      : "보고서 미리보기"),
                    wxDefaultPosition, FromDIP(wxSize(760, 470)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    std::string text;
    if (files)
    {
        text = "manifest.json / 목록과 원문 SHA256\n";
        for (const auto& row : m_review.at("files"))
        {
            text += "\n" + row.at("uri").get<std::string>() + " / " + std::to_string(row.at("bytes").get<int>()) +
                    " B\n" + row.at("sha256").get<std::string>() + "\n";
        }
        if (archive && m_review.at("file_count").get<std::size_t>() > m_review.at("files").size() + 1)
        {
            text += "\n미리보기에는 32개까지 표시합니다. 전체 파일은 manifest.json에서 확인하세요.";
        }
    }
    else
    {
        text = archive ? "프로젝트 복원에 포함되는 파일 " + std::to_string(m_review.at("file_count").get<int>()) +
                            "개 / 미확보 " + std::to_string(m_review.at("missing_count").get<int>()) + "개\n\n"
                       : "인계 보고서의 근거 " + std::to_string(m_review.at("evidence_count").get<int>()) + "건\n\n";
        for (const auto& limit : m_review.at("limitations"))
        {
            text += limit.get<std::string>() + "\n";
        }
        if (archive)
        {
            for (const auto& row : m_review.at("omitted_preview"))
            {
                text += "\n" + row.at("reason").get<std::string>() + " / " +
                        row.at("reference").at("uri").get<std::string>() + "\n";
            }
            if (m_review.at("missing_count").get<std::size_t>() > m_review.at("omitted_preview").size())
            {
                text += "\n전체 누락 원문은 ZIP의 restore-index.json에서 확인하세요.\n";
            }
        }
        else
        {
            for (const auto& row : m_review.at("preview_records"))
            {
                text += "\n" + Kind(row.at("kind")) + " / " + EvidenceName(row) + " / " +
                        CopyState(row.at("copy_state")) + "\n";
            }
            if (m_review.at("evidence_count").get<std::size_t>() > m_review.at("preview_records").size())
            {
                text += "\n미리보기는 32건까지 표시합니다. 전체 목록은 ZIP의 report.json에서 확인하세요.\n";
            }
        }
    }
    auto* content = new wxTextCtrl(&dialog, wxID_ANY, Display(text), wxDefaultPosition, wxDefaultSize,
                                   wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    content->SetName(Display(files ? "인계 파일 목록" : "보고서 내용"));
    layout->Add(content, 1, wxEXPAND | wxALL, FromDIP(12));
    if (!files)
    {
        auto* identifiers = new wxButton(&dialog, wxID_ANY, Display("개정과 원본 해시"));
        layout->Add(identifiers, 0, wxLEFT | wxRIGHT, FromDIP(12));
        identifiers->Bind(wxEVT_BUTTON, [this, &dialog](wxCommandEvent&)
        {
            wxDialog details(&dialog, wxID_ANY, Display("인계 원본 식별 정보"), wxDefaultPosition,
                             FromDIP(wxSize(600, 220)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
            auto* detailLayout = new wxBoxSizer(wxVERTICAL);
            auto* raw = new wxTextCtrl(&details, wxID_ANY,
                Display("설계 개정\n" + m_review.at("revision_id").get<std::string>() +
                        "\n\n원본 SHA-256\n" + m_review.at("content_hash").get<std::string>()),
                wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
            detailLayout->Add(raw, 1, wxEXPAND | wxALL, FromDIP(12));
            detailLayout->Add(details.CreateSeparatedButtonSizer(wxOK), 0, wxEXPAND | wxALL, FromDIP(8));
            details.SetSizer(detailLayout);
            details.CentreOnParent();
            details.ShowModal();
        });
    }
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK), 0, wxEXPAND | wxALL, FromDIP(8));
    dialog.SetSizer(layout);
    dialog.CentreOnParent();
    dialog.ShowModal();
}
