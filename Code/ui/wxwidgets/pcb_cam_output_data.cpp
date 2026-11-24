/** @file @brief PCB 출력의 실제 투영과 보존 파일을 사람 이름과 상태로 표시한다. */
#include "pcb_cam_output_view.h"
#include "drawing_sheet_canvas.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "output_model.h"
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/stattext.h>
#include <algorithm>

namespace
{
void Row(wxListCtrl* table, const std::vector<std::string>& values)
{
    const long row = table->InsertItem(table->GetItemCount(), Display(values.front()));
    for (std::size_t index = 1; index < values.size(); ++index)
    {
        table->SetItem(row, static_cast<int>(index), Display(values.at(index)));
    }
}

std::string Role(const Json& value)
{
    if (value == "conductor")
    {
        return "도체";
    }
    if (value == "solder_mask")
    {
        return "솔더 마스크";
    }
    if (value == "solder_paste")
    {
        return "솔더 페이스트";
    }
    return "기록된 기타 역할";
}

std::string Size(const Json& shape)
{
    if (shape.value("kind", "") == "circle")
    {
        return OutputUi::Text(shape.value("diameter_mm", Json(nullptr)));
    }
    if (shape.value("kind", "") == "capsule")
    {
        return OutputUi::Text(shape.value("finished_length_mm", Json(nullptr))) + " x " +
               OutputUi::Text(shape.value("finished_width_mm", Json(nullptr)));
    }
    return "보존된 외곽 좌표";
}
}

void PcbCamOutputView::RenderLayers(const Json& rows)
{
    const auto selection = DisplaySelection().value("view_layer_id", Json(nullptr));
    m_layers.clear();
    m_layer->Clear();
    m_kicad->DeleteAllItems();
    m_gerber->DeleteAllItems();
    for (const auto& layer : rows)
    {
        const bool included = layer.value("selected", false);
        const auto state = layer.value("state", "unknown");
        const auto side = layer.value("side", Json(nullptr));
        const std::vector<std::string> values{
            OutputUi::Text(layer.value("name", Json(nullptr)), "층 이름 미기록"),
            OutputUi::Text(layer.value("target_label", Json(nullptr)), "검토 후 확인"),
            Role(layer.value("role", Json(nullptr))),
            side == "top"      ? "상면"
            : side == "bottom" ? "하면"
                               : "원본 적층",
            included              ? "포함"
            : state == "not_used" ? "명시 사용 안 함"
                                  : "사용 여부 미정"};
        Row(m_kicad, values);
        Row(m_gerber, values);
        if (included)
        {
            m_layers.push_back(layer.at("id"));
            m_layer->Append(Display(values.front()));
            if (layer.at("id") == selection)
            {
                m_layer->SetSelection(static_cast<int>(m_layers.size() - 1));
            }
        }
    }
}

void PcbCamOutputView::RenderDrills(const Json& pcb)
{
    m_drills->DeleteAllItems();
    const auto names = pcb.value("names", Json::object());
    for (const auto* collection : {"holes", "cutouts"})
    {
        for (const auto& item : pcb.value(collection, Json::array()))
        {
            const auto shape = item.value("shape", Json::object());
            const auto kind = shape.value("kind", "");
            const auto plating = item.value("plating", Json::object()).value("state", "unknown");
            Row(m_drills, {OutputUi::Text(names.value(item.at("id").get<std::string>(), Json(nullptr)), "기계 형상"),
                           kind == "circle"    ? "원형"
                           : kind == "capsule" ? "직선 슬롯"
                                               : "외곽 라우트",
                           Size(shape), OutputUi::Text(item.value("tool_diameter_mm", Json(nullptr))),
                           std::string(collection) == "cutouts" ? "기판 내부 절삭"
                           : plating == "plated"                ? "도금"
                           : plating == "unplated"              ? "비도금"
                                                                : "미정"});
        }
    }
}

void PcbCamOutputView::RenderFiles(const Json& record)
{
    m_files->DeleteAllItems();
    auto artifacts = record.value("artifacts", Json::array());
    if (artifacts.empty() && record.value("manifest", Json(nullptr)).is_object())
    {
        artifacts = record.at("manifest").value("files", Json::array());
    }
    for (const auto& artifact : artifacts)
    {
        auto name = OutputUi::Text(artifact.value("name", artifact.value("uri", Json(nullptr))), "파일 이름 미기록");
        const auto slash = name.find_last_of("/\\");
        if (slash != std::string::npos)
        {
            name = name.substr(slash + 1);
        }
        Row(m_files,
            {name, OutputUi::Text(artifact.value("role", Json(nullptr))),
             OutputUi::Text(artifact.value("bytes", Json(nullptr))),
             artifact.value("sha256", Json(nullptr)).is_string() ? "해시 보존 (별도 검수)" : "파일 해시 미기록"});
    }
    if (artifacts.empty())
    {
        Row(m_files, {"생성된 파일 없음", "Gerber, 드릴, Job을 한 패키지로 출력", "", "생성 후 별도 읽기 검수"});
    }
}

void PcbCamOutputView::SetPreview(const Json& review)
{
    m_refreshing = true;
    m_review = review;
    const auto pcb = review.value("pcb_preview", Json::object());
    m_coordinates->SetLabel(Display(pcb.value("coordinate_policy", "") == "footprint_local_mm_y_up_no_mirror"
                                        ? "선택 부품의 로컬 좌표로 1:1 출력합니다. 배치 원점과 회전을 제거하며 추가 미러링은 적용하지 않습니다."
                                        : "위에서 본 원본 XY 좌표로 1:1 출력합니다. 임의 미러링은 적용하지 않습니다."));
    RenderLayers(pcb.value("layers", Json::array()));
    const auto selected = pcb.value("view_layer_id", Json(nullptr));
    for (std::size_t index = 0; index < m_layers.size(); ++index)
    {
        if (m_layers.at(index) == selected)
        {
            m_layer->SetSelection(static_cast<int>(index));
        }
    }
    RenderDrills(pcb);
    RenderFiles(review);
    const auto pages = review.value("pages", Json::array());
    if (pages.empty())
    {
        m_canvas->Clear("표시할 실제 투영이 없습니다. 누락값과 지원 범위를 확인하세요.");
    }
    else
    {
        m_canvas->SetPages(pages);
    }
    std::string note =
        "고정 원본의 실제 형상 미리보기입니다. 일부 층만 빠뜨린 Job은 생성하지 않습니다.\nGerber/드릴/Job은 함께 "
        "생성하며, 제작 및 측정 조건과 수신 도구 재채움은 별도 확인합니다.";
    const auto issues = OutputUi::Issues(review.value("issues", Json::array()));
    if (!issues.empty())
    {
        note += "\n" + issues;
    }
    m_notice->SetLabel(Display(note));
    m_notice->Wrap(std::max(FromDIP(240), GetClientSize().x - FromDIP(20)));
    m_refreshing = false;
    Layout();
    FitInside();
}

void PcbCamOutputView::SetRecord(const Json& record)
{
    m_refreshing = true;
    m_kicad->DeleteAllItems();
    m_gerber->DeleteAllItems();
    m_drills->DeleteAllItems();
    m_layer->SetSelection(wxNOT_FOUND);
    Row(m_kicad, {"보존 출력의 대응은 파일 및 검수 탭에서 확인", "", "", "", "현재 입력과 별개"});
    Row(m_gerber, {"보존 출력의 대응은 파일 및 검수 탭에서 확인", "", "", "", "현재 입력과 별개"});
    m_coordinates->SetLabel(Display("보존 파일의 좌표 기준은 해당 파일의 검수 기록에서 확인하세요."));
    const auto format = record.value("format", "");
    m_tabs->SetSelection(format == "gerber_job" ? 3 : 0);
    if (format != "gerber_job")
    {
        m_format->SetSelection(format == "kicad_mod" ? 1 : 0);
    }
    SelectionChanged();
    RenderFiles(record);
    m_canvas->Clear("선택한 출력 파일과 검수 기록입니다. 다른 원본의 미리보기를 대신 표시하지 않습니다.");
    m_notice->SetLabel(Display(
        "보존된 출력과 새 읽기 검수 결과는 파일 및 검수 탭에서 확인하세요. 원문과 제조·측정 미정값은 함께 보존됩니다."));
    m_refreshing = false;
    Layout();
    FitInside();
}
