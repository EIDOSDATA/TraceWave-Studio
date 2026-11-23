/** @file @brief 보존 출처, 변경 및 저장 개정을 읽기 전용으로 표시한다. */
#include "project_evidence_dialog.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <map>
#include <wx/display.h>
#include <wx/listctrl.h>
#include <wx/wx.h>

namespace
{
/** @brief 헤더와 실제 데이터 셀을 같은 표에 표시한다. */
wxListCtrl* Table(wxWindow& parent, const std::vector<std::pair<const char*, int>>& columns)
{
    auto* table = new wxListCtrl(&parent, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                                 wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    StudioTheme::Table(*table);
    for (const auto& [title, width] : columns)
    {
        table->AppendColumn(Display(title), wxLIST_FORMAT_LEFT, parent.FromDIP(width));
    }
    return table;
}

/** @brief 변경이나 재계산 없이 전달받은 값만 표시한다. */
void Rows(wxListCtrl& table, const Json& rows)
{
    table.Freeze();
    table.DeleteAllItems();
    for (const auto& values : rows)
    {
        const long row = table.InsertItem(table.GetItemCount(), Display(values.at(0).get<std::string>()));
        for (std::size_t col = 1; col < values.size(); ++col)
        {
            table.SetItem(row, col, Display(values.at(col).get<std::string>()));
        }
    }
    table.Thaw();
}

/** @brief 이력 목록의 원시 명령을 변경 작업의 이름으로 읽는다. */
std::string HistoryAction(const std::string& key, const std::string& operation)
{
    static const std::map<std::string, std::string> operations = {
        {"import", "네트워크 자료 가져오기"}, {"solver", "해석 자료 등록"}, {"transform", "네트워크 변환"},
        {"evaluate", "성능 기준 평가"}, {"circuit_apply", "정합 회로 적용"},
        {"record", "시료 / 교정 기록 저장"}, {"import_record", "측정 자료와 시료 가져오기"},
        {"align", "측정 원본 정렬"}, {"compare", "측정 비교 저장"}
    };
    if (key == "network.library.replace" || key == "measurement.workspace.replace")
    {
        const auto found = operations.find(operation);
        if (found != operations.end())
        {
            return found->second;
        }
    }
    static const std::map<std::string, std::string> names = {
        {"target.set", "목표 구성"}, {"target.remove", "목표 삭제"}, {"target.constraints.set", "목표 조건 편집"},
        {"object.create", "설계 항목 추가"}, {"object.update", "설계 항목 변경"}, {"object.delete", "설계 항목 삭제"},
        {"geometry.set", "형상 변경"}, {"geometry.remove", "형상 삭제"}, {"layer.set", "층 변경"},
        {"layer.remove", "층 삭제"}, {"port.set", "급전 변경"}, {"port.remove", "급전 삭제"},
        {"material.set", "재료 변경"}, {"material.remove", "재료 삭제"}, {"parameter.set", "설계 변수 설정"},
        {"metadata.set", "프로젝트 속성 변경"}, {"metadata.describe", "프로젝트 설명 변경"},
        {"board.set", "기판 변경"}, {"stackup.set", "적층 변경"}, {"template.apply", "후보 형상 채택"},
        {"network.library.replace", "네트워크 자료 변경"}, {"measurement.workspace.replace", "측정 자료 변경"}
    };
    const auto found = names.find(key);
    return found == names.end() ? "프로젝트 변경" : found->second;
}

wxPanel* Page(StudioNotebook& pages, const char* label)
{
    auto* page = new wxPanel(&pages);
    page->SetSizer(new wxBoxSizer(wxVERTICAL));
    StudioTheme::BindSurface(*page);
    pages.AddPage(page, Display(label));
    return page;
}

wxTextCtrl* ReadOnly(wxWindow& parent, const char* name, const wxString& value = wxEmptyString)
{
    auto* text = new wxTextCtrl(&parent, wxID_ANY, value, wxDefaultPosition, wxDefaultSize,
                                wxTE_READONLY | wxTE_MULTILINE);
    text->SetName(Display(name));
    return text;
}
}

int ShowProjectEvidence(wxWindow* parent, const Json& evidence, std::size_t page)
{
    wxDialog dialog(parent, wxID_ANY, Display("출처와 채택 이력 / 저장본 확인"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("project.evidence.dialog");
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    auto* root = new wxBoxSizer(wxVERTICAL);
    const int pad = dialog.FromDIP(StudioTheme::PanelPadding);
    auto* title = new wxStaticText(&dialog, wxID_ANY, Display("원문과 현재 프로젝트 개정"));
    StudioTheme::Title(*title);
    root->Add(title, 0, wxLEFT | wxTOP, pad);
    auto* revision = new wxStaticText(&dialog, wxID_ANY,
        Display("현재 개정 " + evidence.at("revision_id").get<std::string>().substr(0, 8)));
    revision->SetToolTip(Display(evidence.at("revision_id").get<std::string>()));
    StudioTheme::BindSecondary(*revision);
    root->Add(revision, 0, wxEXPAND | wxALL, pad);
    auto* choice = new wxChoice(&dialog, wxID_ANY);
    choice->SetName("project.evidence.source");
    const auto& records = evidence.at("records");
    for (const auto& record : records)
    {
        choice->Append(Display(record.at("label").get<std::string>()));
    }
    choice->Enable(!records.empty());
    if (records.empty())
    {
        choice->Append(Display("보존된 채택 또는 목표 출처 없음"));
    }
    choice->SetSelection(0);
    root->Add(choice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);

    auto* tabs = new StudioNotebook(&dialog);
    root->Add(tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
    auto* adoption = Page(*tabs, "원문 / 채택값");
    auto* values = Table(*adoption, {{"항목", 145}, {"원문 / 종류", 170}, {"채택 당시", 220}, {"현재 값", 270}});
    adoption->GetSizer()->Add(values, 2, wxEXPAND | wxALL, pad);
    auto* original = ReadOnly(*adoption, "보존 원문과 선택 행 상세");
    adoption->GetSizer()->Add(original, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* assumptions = Page(*tabs, "가정 / 생략");
    auto* assumptionText = ReadOnly(*assumptions, "생성 당시 가정과 생략");
    assumptions->GetSizer()->Add(assumptionText, 1, wxEXPAND | wxALL, pad);

    auto* changes = Page(*tabs, "변경 이력");
    auto* historyNote = new wxStaticText(changes, wxID_ANY,
        wxString::Format(Display("현재 이력 %d건 중 최근 최대 24건 / 다시 실행 가능 %d건"),
                        evidence.at("history_total").get<int>(), evidence.at("redo_count").get<int>()));
    StudioTheme::BindSecondary(*historyNote);
    changes->GetSizer()->Add(historyNote, 0, wxALL, pad);
    auto* history = Table(*changes, {{"작업", 175}, {"대상", 136}, {"접수 시각", 190}, {"사유", 208}, {"적용 개정", 100}});
    const auto historyContext = evidence.value("history_context", Json::array());
    const auto& historyRows = evidence.at("history");
    auto briefHistory = Json::array();
    for (std::size_t index = 0; index < historyRows.size(); ++index)
    {
        const auto& row = historyRows.at(index);
        const auto context = index < historyContext.size() ? historyContext.at(index) : Json::object();
        const auto name = context.value("name", std::string());
        const auto reason = context.value("reason", std::string());
        const auto timestamp = context.value("timestamp", std::string());
        briefHistory.push_back({HistoryAction(row.at(2).get<std::string>(), context.value("operation", std::string())),
            name.empty() ? "기록 상세" : name, timestamp.empty() ? "미기록" : timestamp,
            reason.empty() ? "미기록" : reason, row.at(1).get<std::string>().substr(0, 8)});
    }
    Rows(*history, briefHistory);
    changes->GetSizer()->Add(history, 2, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* changeDetail = ReadOnly(*changes, "선택 변경의 개정 / 명령 / 대상",
                                  Display("변경 행을 선택하면 전체 개정 ID와 명령을 읽을 수 있습니다."));
    changes->GetSizer()->Add(changeDetail, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    history->Bind(wxEVT_LIST_ITEM_SELECTED, [&](wxListEvent& event)
    {
        const auto index = static_cast<std::size_t>(event.GetIndex());
        const auto& row = historyRows.at(index);
        const auto& brief = briefHistory.at(index);
        changeDetail->ChangeValue(Display(brief.at(0).get<std::string>() + " / " + brief.at(1).get<std::string>() +
            "\n접수 시각  " + brief.at(2).get<std::string>() + "\n사유  " + brief.at(3).get<std::string>() +
            "\n변경 전  " + row.at(0).get<std::string>() + "\n변경 후  " +
            row.at(1).get<std::string>() + "\n명령  " + row.at(2).get<std::string>() + "\n대상 ID  " +
            (index < historyContext.size() ? historyContext.at(index).value("target_id", std::string())
                                            : row.at(3).get<std::string>())));
    });

    auto* recovery = Page(*tabs, "저장본 / 복구 후보");
    auto* status = new wxStaticText(recovery, wxID_ANY,
        Display(evidence.at("saved_revision") == evidence.at("revision_id")
          ? "현재 적용 개정과 저장본이 일치합니다."
          : "현재의 영속 적용 개정과 저장 기준점이 다릅니다. 두 개정의 속성을 확인하세요."));
    StudioTheme::BindSecondary(*status);
    recovery->GetSizer()->Add(status, 0, wxALL, pad);
    auto* saved = Table(*recovery, {{"항목", 132}, {"정상 저장본", 310}, {"현재의 영속 적용 개정", 350}});
    Rows(*saved, evidence.at("recovery"));
    saved->SetMinSize(dialog.FromDIP(wxSize(-1, 82)));
    recovery->GetSizer()->Add(saved, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    const auto recoveryDetails = evidence.value("recovery_details", Json::object());
    const auto recoveryRows = recoveryDetails.value("rows", Json::array());
    const auto recoverySummary = recoveryRows.empty() ? Display("표시할 속성 변경 없음") :
        wxString::Format(Display("속성 변경 %zu건%s"), recoveryRows.size(),
            recoveryDetails.value("has_more", false) ? Display(" 표시 / 나머지 변경 있음") : wxString());
    auto* changesLabel = new wxStaticText(recovery, wxID_ANY, recoverySummary);
    StudioTheme::Heading(*changesLabel);
    recovery->GetSizer()->Add(changesLabel, 0, wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* detailTable = Table(*recovery, {{"분류", 100}, {"대상", 155}, {"변경 항목", 145},
                                        {"저장본", 195}, {"현재 개정", 195}});
    detailTable->SetName("project.recovery.changes");
    Rows(*detailTable, recoveryRows);
    detailTable->SetMinSize(dialog.FromDIP(wxSize(-1, 88)));
    recovery->GetSizer()->Add(detailTable, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* savedDetail = ReadOnly(*recovery, "project.recovery.detail",
        Display(recoveryRows.empty() ? "저장본과 현재 개정의 표시 대상 값이 같습니다."
                                     : "변경 행을 선택하면 저장본과 현재 값의 상세를 읽을 수 있습니다."));
    savedDetail->SetMinSize(dialog.FromDIP(wxSize(-1, 96)));
    recovery->GetSizer()->Add(savedDetail, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    detailTable->Bind(wxEVT_LIST_ITEM_SELECTED, [savedDetail, &recoveryRows](wxListEvent& event)
    {
        const auto& row = recoveryRows.at(static_cast<std::size_t>(event.GetIndex()));
        const auto& target = row.at(1).get_ref<const std::string&>();
        savedDetail->ChangeValue(Display(row.at(0).get<std::string>() + (target.empty() ? "" : " / " + target) +
            " / " + row.at(2).get<std::string>() + "\n저장본  " + row.at(3).get<std::string>() +
            "\n현재 개정  " + row.at(4).get<std::string>()));
    });
    auto* instructions = new wxStaticText(recovery, wxID_ANY,
        Display("저장 상태를 확인한 후 현재 개정을 다시 읽거나, 보존 묶음을 별도 작업 영역으로 복원할 수 있습니다."));
    StudioTheme::BindSecondary(*instructions);
    instructions->Wrap(dialog.FromDIP(745));
    recovery->GetSizer()->Add(instructions, 0, wxLEFT | wxRIGHT | wxBOTTOM, pad);

    const auto update = [&]()
    {
        if (records.empty())
        {
            original->ChangeValue(Display("이 프로젝트에 표시할 원문 또는 채택 기록이 없습니다."));
            assumptionText->ChangeValue(Display("보존된 가정 또는 생략 기록이 없습니다."));
            return;
        }
        const auto& record = records.at(static_cast<std::size_t>(choice->GetSelection()));
        Rows(*values, record.at("values"));
        original->ChangeValue(Display(record.at("source").get<std::string>()));
        const auto note = record.at("assumptions").get<std::string>();
        assumptionText->ChangeValue(Display(note.empty() ? "이 기록에 명시된 가정 또는 생략 없음" : note));
    };
    choice->Bind(wxEVT_CHOICE, [&](wxCommandEvent&) { update(); });
    values->Bind(wxEVT_LIST_ITEM_SELECTED, [&](wxListEvent& event)
    {
        const auto& record = records.at(static_cast<std::size_t>(choice->GetSelection()));
        const auto& row = record.at("values").at(static_cast<std::size_t>(event.GetIndex()));
        original->ChangeValue(Display("항목  " + row.at(0).get<std::string>() +
             "\n원문 / 종류  " + row.at(1).get<std::string>() + "\n채택 당시  " + row.at(2).get<std::string>() +
             "\n현재 값  " + row.at(3).get<std::string>() + "\n\n" + record.at("source").get<std::string>()));
    });
    update();
    tabs->SetSelection(page);

    auto* close = new wxButton(&dialog, wxID_CLOSE, Display("닫기"));
    StudioTheme::Button(*close);
    auto* footer = new wxBoxSizer(wxHORIZONTAL);
    footer->AddStretchSpacer();
    footer->Add(close, 0);
    if (page == 3)
    {
        auto* reopen = new wxButton(&dialog, wxID_OK, Display("현재 개정 다시 읽기"));
        StudioTheme::Button(*reopen, true);
        footer->Add(reopen, 0, wxLEFT, pad);
        auto* restore = new wxButton(&dialog, wxID_APPLY, Display("보존 묶음 복원"));
        StudioTheme::Button(*restore);
        footer->Add(restore, 0, wxLEFT, pad);
        restore->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) { dialog.EndModal(wxID_APPLY); });
    }
    close->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) { dialog.EndModal(wxID_CANCEL); });
    dialog.SetEscapeId(wxID_CLOSE);
    root->Add(footer, 0, wxEXPAND | wxALL, pad);
    dialog.SetSizer(root);
    const auto geometry = wxDisplay(parent).GetClientArea().Deflate(dialog.FromDIP(16));
    const auto ideal = dialog.FromDIP(wxSize(950, 645));
    dialog.SetSize(std::min(ideal.x, geometry.width), std::min(ideal.y, geometry.height));
    dialog.CentreOnParent();
    return dialog.ShowModal();
}
