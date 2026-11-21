/** @file @brief 원문 선택과 명시적인 대상 대응을 네이티브 위젯으로 표시한다. */
#include "pcb_import_dialog.h"
#include "design_canvas.h"
#include "output_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>

namespace
{
wxTextCtrl* Readable(wxWindow* parent, const std::string& text, int height)
{
    return new wxTextCtrl(parent, wxID_ANY, Display(text), wxDefaultPosition, parent->FromDIP(wxSize(-1, height)),
                          wxTE_MULTILINE | wxTE_READONLY);
}

void FitPage(wxWindow* window)
{
    window->Layout();
    if (auto* scroll = dynamic_cast<wxScrolledWindow*>(window))
    {
        scroll->FitInside();
    }
}
}

void PcbImportDialog::BuildSource(wxWindow* page)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* inputs = new wxWrapSizer(wxHORIZONTAL);
    m_format = new wxChoice(page, wxID_ANY);
    m_formats = {"kicad_pcb", "kicad_mod", "gerber_job", "gerber_x2", "xnc"};
    for (const auto& label : {"KiCad 보드", "KiCad 풋프린트", "Gerber Job", "Gerber X2", "Excellon / XNC"})
    {
        m_format->Append(Display(label));
    }
    for (const auto& pattern : m_context.value("vendor_patterns", Json::array()))
    {
        m_formats.push_back(pattern.at("format").get<std::string>());
        m_format->Append(Display(pattern.at("label").get<std::string>()));
    }
    m_format->SetName(Display("가져올 형식 또는 제조사 안테나 예제"));
    m_format->SetSelection(0);
    m_browse = new wxButton(page, wxID_ANY, Display("파일 선택"));
    m_uploadButton = new wxButton(page, wxID_ANY, Display("원문 전송 / 이어 보내기"));
    m_parseButton = new wxButton(page, wxID_ANY, Display("보존 원문 읽기"));
    for (wxWindow* control : std::vector<wxWindow*>{m_format, m_browse, m_uploadButton, m_parseButton})
    {
        inputs->Add(control, 0, wxRIGHT | wxBOTTOM, FromDIP(8));
    }
    layout->Add(inputs, 0, wxEXPAND | wxALL, FromDIP(12));
    m_formatDetail = Readable(page, "", 64);
    layout->Add(m_formatDetail, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    DescribeFormat();
    m_uploadChoice = new wxChoice(page, wxID_ANY);
    m_uploadChoice->Append(Display("새 원문 전송"));
    m_uploadIds.emplace_back();
    for (const auto& entry : m_context.value("uploads", Json::array()))
    {
        const auto label = OutputUi::Text(entry.value("label", entry.value("name", Json(nullptr))),
                                          "보존 전송 " + std::to_string(m_uploadIds.size()));
        m_uploadChoice->Append(Display(label + " / " + entry.value("format", "") + " / " +
                                       OutputUi::State(entry.value("status", "unknown"))));
        m_uploadIds.push_back(entry.at("upload_id").get<std::string>());
    }
    m_uploadChoice->SetSelection(0);
    layout->Add(new wxStaticText(page, wxID_ANY, Display("이전에 보존한 전송")), 0, wxLEFT | wxRIGHT, FromDIP(12));
    layout->Add(m_uploadChoice, 0, wxEXPAND | wxALL, FromDIP(12));
    m_fileTable =
        new wxListCtrl(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 200)), wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_fileTable);
    for (const auto& col : std::vector<std::pair<std::string, int>>{
             {"원문 파일", 300}, {"바이트", 100}, {"보존한 바이트", 120}, {"SHA256", 510}})
    {
        m_fileTable->AppendColumn(Display(col.first), wxLIST_FORMAT_LEFT, FromDIP(col.second));
    }
    layout->Add(m_fileTable, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_summary = Readable(page,
                         "원문과 읽기 보고서를 함께 보존합니다. 최대 40개 파일, 전체 원문과 보고서 16 MiB. 전송과 "
                         "읽기는 현재 설계를 변경하지 않습니다. 자동 층 대응이나 제작 합격 판정은 하지 않습니다.",
                         110);
    layout->Add(m_summary, 0, wxEXPAND | wxALL, FromDIP(12));
    page->SetSizer(layout);
    m_browse->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Browse();
                   });
    m_uploadButton->Bind(wxEVT_BUTTON,
                         [this](wxCommandEvent&)
                         {
                             Upload();
                         });
    m_parseButton->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            Parse();
                        });
    m_format->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       DescribeFormat();
                       Changed();
                   });
    m_uploadChoice->Bind(
        wxEVT_CHOICE,
        [this](wxCommandEvent&)
        {
            if (m_loading || !Editable() || m_pending)
            {
                return;
            }
            const auto selected = m_uploadIds.at(static_cast<std::size_t>(m_uploadChoice->GetSelection()));
            if (!ConfirmDiscard())
            {
                const auto found = std::find(m_uploadIds.begin(), m_uploadIds.end(), m_upload);
                m_uploadChoice->SetSelection(
                    found == m_uploadIds.end() ? 0 : static_cast<int>(found - m_uploadIds.begin()));
                return;
            }
            m_poll.Stop();
            m_upload = selected;
            m_files.clear();
            m_uploadState = nullptr;
            m_mappingLoaded = false;
            m_boardConfirmed->SetValue(false);
            Changed();
            m_dirty = false;
            RenderFiles();
            if (!selected.empty())
            {
                ReadUpload(selected);
            }
            else
            {
                m_summary->ChangeValue(Display("새 원문 파일을 선택하세요. 이전 전송과 원문은 보존됩니다."));
                UpdateActions();
            }
        });
}

void PcbImportDialog::BuildMapping(wxWindow* page)
{
    m_mappingPage = page;
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(Readable(page,
                         "현재 기판과 좌표계를 적용 대상으로 사용합니다. 기판 외곽을 자동 교체하지 않습니다. "
                         "소스층마다 기존 층을 직접 선택하고, 소스 넷마다 기존 넷 또는 명시적인 미할당을 선택하세요.",
                         90),
                0, wxEXPAND | wxALL, FromDIP(12));
    m_boardConfirmed = new wxCheckBox(page, wxID_ANY, Display("현재 기판 / 좌표계에 적용함을 확인"));
    layout->Add(m_boardConfirmed, 0, wxALL, FromDIP(12));
    m_mappingRows = new wxPanel(page);
    m_mappingRows->SetSizer(new wxBoxSizer(wxVERTICAL));
    layout->Add(m_mappingRows, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_placement = new wxPanel(page);
    auto* position = new wxWrapSizer(wxHORIZONTAL);
    position->Add(new wxStaticText(m_placement, wxID_ANY, Display("원본 배치 X / Y / 회전")), 0, wxALL,
                  FromDIP(6));
    m_x = new wxTextCtrl(m_placement, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(90, -1)));
    m_y = new wxTextCtrl(m_placement, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(90, -1)));
    m_rotation = new wxTextCtrl(m_placement, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(90, -1)));
    m_lengthUnit = new wxChoice(m_placement, wxID_ANY);
    for (const auto& unit : {"mm", "um", "mil", "m"})
    {
        m_lengthUnit->Append(unit);
    }
    m_lengthUnit->SetSelection(0);
    m_angleUnit = new wxChoice(m_placement, wxID_ANY);
    m_angleUnit->Append("deg");
    m_angleUnit->Append("rad");
    m_angleUnit->SetSelection(0);
    m_side = new wxChoice(m_placement, wxID_ANY);
    m_side->Append(Display("배치 면 선택"));
    m_side->Append(Display("상면"));
    m_side->Append(Display("하면"));
    m_side->SetSelection(0);
    for (wxWindow* control : std::vector<wxWindow*>{m_x, m_y, m_lengthUnit, m_rotation, m_angleUnit, m_side})
    {
        position->Add(control, 0, wxALL, FromDIP(4));
    }
    m_placement->SetSizer(position);
    m_placement->Hide();
    layout->Add(m_placement, 0, wxEXPAND | wxALL, FromDIP(8));
    page->SetSizer(layout);
    m_boardConfirmed->Bind(wxEVT_CHECKBOX,
                           [this](wxCommandEvent&)
                           {
                               Changed();
                           });
    for (auto* text : {m_x, m_y, m_rotation})
    {
        text->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
    }
    for (auto* choice : {m_lengthUnit, m_angleUnit, m_side})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Changed();
                     });
    }
}

void PcbImportDialog::BuildReview(wxWindow* page)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_sceneChoice = new wxChoice(page, wxID_ANY);
    m_sceneChoice->Append(Display("가져오기 후보"));
    m_sceneChoice->Append(Display("현재 원본"));
    m_sceneChoice->SetSelection(0);
    layout->Add(m_sceneChoice, 0, wxALL, FromDIP(8));
    m_canvas = new DesignCanvas(page);
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetMinSize(FromDIP(wxSize(280, 220)));
    layout->Add(m_canvas, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_changes =
        new wxListCtrl(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 130)), wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_changes);
    for (const auto& column :
         std::vector<std::pair<std::string, int>>{{"변경 항목", 210}, {"변경 전", 260}, {"변경 후", 350}, {"단위", 80}})
    {
        m_changes->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_changes, 0, wxEXPAND | wxALL, FromDIP(8));
    layout->Add(
        new wxStaticText(page, wxID_ANY, Display("읽기 과정의 손실 / 생략 - 원문은 보존하며 항목마다 확인합니다.")), 0,
        wxALL, FromDIP(8));
    m_losses = new wxCheckListBox(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 110)));
    layout->Add(m_losses, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    layout->Add(new wxStaticText(page, wxID_ANY, Display("가져오기 사유")), 0, wxALL, FromDIP(8));
    m_reason = new wxTextCtrl(page, wxID_ANY, wxEmptyString);
    layout->Add(m_reason, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_issues = Readable(page, "원문 읽기와 명시 대응을 마친 뒤 후보를 검토하세요.", 90);
    layout->Add(m_issues, 0, wxEXPAND | wxALL, FromDIP(8));
    page->SetSizer(layout);
    m_sceneChoice->Bind(wxEVT_CHOICE,
                        [this](wxCommandEvent&)
                        {
                            ShowScene();
                        });
    m_reason->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
    m_losses->Bind(wxEVT_CHECKLISTBOX,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
}

void PcbImportDialog::BuildOriginal(wxWindow* page)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_source = Readable(page,
                        "원문 파일과 읽기 보고서의 SHA256을 보존합니다. 변환 이후에는 가져온 상태와 사용자의 수정을 "
                        "구분합니다. 제작 조건 / 측정 정확도 / RF 성능은 이 가져오기에서 확인하지 않습니다.",
                        180);
    layout->Add(m_source, 0, wxEXPAND | wxALL, FromDIP(12));
    m_advanced = new wxCollapsiblePane(page, wxID_ANY, Display("고급 원문 상세"));
    auto* body = m_advanced->GetPane();
    auto* content = new wxBoxSizer(wxVERTICAL);
    m_raw = Readable(body, "", 300);
    content->Add(m_raw, 1, wxEXPAND);
    body->SetSizer(content);
    m_advanced->Collapse(true);
    layout->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(12));
    page->SetSizer(layout);
    m_advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                     [page](wxCollapsiblePaneEvent&)
                     {
                         FitPage(page);
                     });
}

void PcbImportDialog::RenderMapping(const Json& response)
{
    if (m_mappingLoaded)
    {
        return;
    }
    const auto sources = response.value("mapping_sources", Json(nullptr));
    if (!sources.is_object())
    {
        SetStatus("원문 읽기는 완료되었지만 대응 목록을 확인할 수 없습니다. 원문을 다시 조회하세요.");
        return;
    }
    m_loading = true;
    m_mappingRows->GetSizer()->Clear(true);
    m_layerRows.clear();
    m_netRows.clear();
    for (const auto& kind : {std::string("layers"), std::string("nets")})
    {
        m_mappingRows->GetSizer()->Add(
            new wxStaticText(m_mappingRows, wxID_ANY,
                             Display(kind == "layers" ? "원문 층 -> 기존 층" : "원문 넷 -> 기존 넷 / 미할당")),
            0, wxTOP | wxBOTTOM, FromDIP(8));
        for (const auto& source : sources.value(kind, Json::array()))
        {
            MappingRow row;
            row.source = source.at("source").get<std::string>();
            auto* line = new wxBoxSizer(wxHORIZONTAL);
            auto* label = new wxStaticText(m_mappingRows, wxID_ANY,
                                           Display(OutputUi::Text(source.value("label", Json(nullptr)),
                                                                  row.source.empty() ? "넷 이름 미기록" : row.source)),
                                           wxDefaultPosition, FromDIP(wxSize(240, -1)), wxST_ELLIPSIZE_END);
            label->SetToolTip(label->GetLabel());
            line->Add(label, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(8));
            row.choice = new wxChoice(m_mappingRows, wxID_ANY);
            row.choice->Append(Display("대상 선택 필요"));
            row.targets.push_back(nullptr);
            if (kind == "nets")
            {
                row.choice->Append(Display("명시적인 넷 미할당"));
                row.targets.push_back(nullptr);
            }
            auto targets = m_context.value(kind, Json::array());
            if (kind == "layers")
            {
                for (const auto& artwork : m_context.value("artwork_layers", Json::array()))
                {
                    if (artwork.value("use_state", "") == "used")
                    {
                        targets.push_back(artwork);
                    }
                }
            }
            for (const auto& target : targets)
            {
                if (kind == "layers" && target.value("role", "") == "dielectric")
                {
                    continue;
                }
                const auto role = target.value("role", "");
                const auto suffix = role == "conductor"      ? "도체"
                                    : role == "solder_mask"  ? "솔더 마스크"
                                    : role == "solder_paste" ? "솔더 페이스트"
                                                             : "";
                row.choice->Append(Display(OutputUi::Text(target.value("name", Json(nullptr)), "임시 이름") +
                                           (kind == "layers" ? " / " + std::string(suffix) : "")));
                row.targets.push_back(target.at("id"));
            }
            row.choice->SetSelection(0);
            row.choice->Bind(wxEVT_CHOICE,
                             [this](wxCommandEvent&)
                             {
                                 Changed();
                             });
            line->Add(row.choice, 1, wxEXPAND);
            m_mappingRows->GetSizer()->Add(line, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
            (kind == "layers" ? m_layerRows : m_netRows).push_back(row);
        }
    }
    m_losses->Clear();
    m_lossKeys.clear();
    for (const auto& loss : sources.value("losses", Json::array()))
    {
        m_losses->Append(Display(OutputUi::Text(loss.value("message", Json(nullptr)), "변환 시 정보 누락")));
        m_lossKeys.push_back(loss.at("id").get<std::string>());
    }
    m_side->Show(!VendorFormat());
    m_placement->Show(response.value("format", "") == "kicad_mod" || VendorFormat());
    m_placement->Layout();
    m_mappingLoaded = true;
    m_loading = false;
    FitPage(m_mappingPage);
    FitPage(m_tabs->GetPage(2));
}
