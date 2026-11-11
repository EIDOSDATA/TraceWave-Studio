/** @file @brief 서버 후보의 단면과 변경 사유를 물리 승인과 구분해 표시한다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include <wx/dcbuffer.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <algorithm>

wxPanel* PcbSelectionDialog::BuildReviewPage()
{
    auto* panel = new wxPanel(m_notebook);
    auto* layout = new wxBoxSizer(wxHORIZONTAL);
    auto* section = new wxBoxSizer(wxVERTICAL);
    section->Add(new wxStaticText(panel, wxID_ANY, Display("후보 단면 (식별용 도식, 두께 비례 아님)")), 0, wxBOTTOM,
                 FromDIP(8));
    m_section = new wxPanel(panel, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(350, -1)));
    m_section->SetName("pcb.section");
    m_section->SetBackgroundStyle(wxBG_STYLE_PAINT);
    m_section->Bind(wxEVT_PAINT, &PcbSelectionDialog::PaintSection, this);
    section->Add(m_section, 1, wxEXPAND);
    layout->Add(section, 0, wxEXPAND | wxALL, FromDIP(10));
    m_review = new wxTextCtrl(
        panel, wxID_ANY,
        Display("변경 미리보기를 실행하면 기존 참조, 미정 치수, 출처 용량과 적용 가능 여부를 확인할 수 있습니다."),
        wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
    m_review->SetName("pcb.review");
    layout->Add(m_review, 1, wxEXPAND | wxALL, FromDIP(10));
    panel->SetSizer(layout);
    return panel;
}

/** @brief 표시용 mm 값은 서버에서만 받고 미정 구간의 좌표를 계산하지 않는다. */
void PcbSelectionDialog::RenderPreview(const Json& result)
{
    m_sectionLayers = m_model.CandidateLayers();
    m_section->Refresh();
    std::string review = result.value("can_apply", false) ? "프로젝트에 적용할 수 있습니다.\n"
                                                          : "해결해야 할 항목이 있어 적용할 수 없습니다.\n";
    review += "CAD 생성과 EM 해석은 별도 입력 검사를 거칩니다. 이 화면은 해석 준비 완료를 승인하지 않습니다.\n\n";
    review += "저장 한도: 프로젝트 32 KiB, 현재/과거 출처 합계 12 KiB입니다. 큰 적층이나 근거는 축약해서 적용하지 않고 "
              "명시적으로 거부합니다.\n\n";
    if (result.contains("size"))
    {
        review += "프로젝트 크기: " + PcbView::Text(result.at("size"), "document_bytes") + " / " +
                  PcbView::Text(result.at("size"), "document_limit_bytes") + " bytes\n";
    }
    review += "모델 층 두께 합계: " + PcbView::Text(result, "modeled_total_thickness_mm") + " mm\n";
    if (result.contains("changes"))
    {
        const auto& changes = result.at("changes");
        for (const char* collection : {"materials", "stackup", "ports"})
        {
            if (changes.contains(collection))
            {
                const auto& counts = changes.at(collection);
                review += "\n" + std::string(collection) + ": ";
                for (const char* change : {"added", "removed", "changed"})
                {
                    if (counts.contains(change))
                    {
                        review += std::string(change) + " " + std::to_string(counts.at(change).size()) + "  ";
                    }
                }
            }
        }
    }
    review += "\n\n층 목록 (아래에서 위)\n";
    for (const auto& layer : m_sectionLayers)
    {
        review += "- " + PcbView::Text(layer, "name") + ": 두께 " + PcbView::Text(layer, "thickness_mm") +
                  " mm, 아래 z " + PcbView::Text(layer, "z_min_mm") + " mm\n";
    }
    if (result.contains("retained_selections") && !result.at("retained_selections").empty())
    {
        review += "\n기존 객체가 사용하는 이전 출처 선택 " + std::to_string(result.at("retained_selections").size()) +
                  "개를 함께 보존합니다.\n";
    }
    review += "\n확인할 사항\n";
    for (const auto& issue : result.at("issues"))
    {
        review += (issue.value("severity", "warning") == "blocker" ? "[적용 차단] " : "[확인 필요] ") +
                  DiagnosticMessage(issue) + "\n";
    }
    if (result.contains("input_checks"))
    {
        const auto& checks = result.at("input_checks");
        for (const char* scope : {"geometry", "step", "em"})
        {
            if (checks.contains(scope))
            {
                const auto& check = checks.at(scope);
                review += "\n" + std::string(scope) + " 입력 검사: " + PcbView::Text(check, "input_status") + "\n";
                if (check.contains("diagnostics"))
                {
                    for (const auto& diagnostic : check.at("diagnostics"))
                    {
                        review += "- " + DiagnosticMessage(diagnostic) + "\n";
                    }
                }
                if (check.value("diagnostics_truncated", false))
                {
                    review += "추가 진단은 기존 입력 검사 화면에서 확인하세요.\n";
                }
            }
        }
    }
    m_review->ChangeValue(Display(review));
    m_notebook->SetSelection(4);
    SetStatus(result.value("can_apply", false)
                  ? "변경 내용과 미정 항목을 확인한 뒤 적용하세요. 입력을 수정하면 다시 미리보기해야 합니다."
                  : "적용을 차단하는 항목이 있습니다. 검토 내용을 확인하고 해당 입력을 수정하세요.");
}

void PcbSelectionDialog::PaintSection(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(m_section);
    dc.SetBackground(wxBrush(wxColour(245, 247, 250)));
    dc.Clear();
    const wxSize size = m_section->GetClientSize();
    if (m_sectionLayers.empty())
    {
        dc.DrawText(Display("미리보기 후 후보 단면 표시"), FromDIP(12), FromDIP(12));
        return;
    }
    const int rowHeight =
        std::max(FromDIP(20), std::min(FromDIP(56), (size.y - FromDIP(56)) / static_cast<int>(m_sectionLayers.size())));
    int y = FromDIP(32);
    std::size_t shown = 0;
    for (auto item = m_sectionLayers.rbegin(); item != m_sectionLayers.rend(); ++item)
    {
        const auto& layer = *item;
        const std::string role = layer.value("role", std::string());
        const bool unknown = !layer.contains("thickness_mm") || layer.at("thickness_mm").is_null();
        const wxColour color = unknown ? wxColour(222, 226, 232)
                                       : (role == "conductor" ? wxColour(217, 155, 83) : wxColour(139, 181, 167));
        dc.SetPen(wxPen(wxColour(102, 115, 126), 1, unknown ? wxPENSTYLE_SHORT_DASH : wxPENSTYLE_SOLID));
        dc.SetBrush(wxBrush(color));
        dc.DrawRectangle(FromDIP(10), y, std::max(10, size.x - FromDIP(20)), rowHeight - FromDIP(4));
        const wxString label =
            Display(PcbView::Text(layer, "name") + " / " + PcbView::Text(layer, "thickness_mm") + " mm");
        dc.SetClippingRegion(FromDIP(16), y, std::max(1, size.x - FromDIP(32)), rowHeight);
        dc.DrawText(label, FromDIP(16), y + FromDIP(3));
        dc.DestroyClippingRegion();
        ++shown;
        y += rowHeight;
        if (y > size.y - rowHeight)
        {
            break;
        }
    }
    dc.DrawText(Display("표시 " + std::to_string(shown) + " / 전체 " + std::to_string(m_sectionLayers.size()) + "층"),
                FromDIP(12), FromDIP(8));
    if (shown < m_sectionLayers.size())
    {
        dc.DrawText(Display("전체 층은 오른쪽 검토 목록에서 확인"), FromDIP(12),
                    std::max(FromDIP(32), size.y - FromDIP(20)));
    }
}
