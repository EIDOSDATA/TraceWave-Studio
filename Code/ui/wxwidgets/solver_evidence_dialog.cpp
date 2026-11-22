/** @file @brief 봉인 개정, 당시 조건, 계산 입력과 필드별 출처를 표시한다. */
#include "solver_evidence_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/notebook.h>
#include <wx/weakref.h>
#include <wx/wx.h>
#include <tuple>

namespace
{
using Callback = std::function<void(const Json&)>;

wxTextCtrl* ReadOnly(wxWindow* parent, const char* name, const std::string& value = "")
{
    auto* text = new wxTextCtrl(parent, wxID_ANY, Display(value), wxDefaultPosition, wxDefaultSize,
                                wxTE_MULTILINE | wxTE_READONLY);
    text->SetName(name);
    return text;
}

void Present(wxTextCtrl* text, const std::string& value)
{
    text->ChangeValue(Display(value));
    text->SetInsertionPoint(0);
    text->ShowPosition(0);
}

std::string Kind(const std::string& kind)
{
    if (kind == "port")
    {
        return "급전";
    }
    if (kind == "material")
    {
        return "재료";
    }
    if (kind == "terminal")
    {
        return "양단 도체";
    }
    return kind == "geometry" ? "해석 도체" : "적층";
}

void Line(std::string& text, const Json& values, const char* key, const char* label, const char* unit = "")
{
    if (values.contains(key))
    {
        text += std::string(label) + "  " + values.at(key).dump(-1, ' ', false, Json::error_handler_t::replace) + unit + "\n";
    }
}

std::string UsedValues(const Json& data)
{
    const auto& used = data.at("used");
    std::string text;
    Line(text, used, "resistance_ohm", "계산 급전 저항", " ohm");
    Line(text, used, "start_mm", "급전 시작점", " mm");
    Line(text, used, "stop_mm", "급전 끝점", " mm");
    Line(text, used, "direction", "급전 방향");
    Line(text, used, "reference_plane", "기준면");
    Line(text, used, "epsilon_r", "계산 상대 유전율");
    Line(text, used, "tan_delta", "계산 손실 탄젠트");
    Line(text, used, "conductivity_s_per_m", "계산 전도도", " S/m");
    Line(text, used, "width_mm", "계산 도체 폭", " mm");
    Line(text, used, "outer_radius_mm", "계산 비아 바깥 반경", " mm");
    Line(text, used, "inner_radius_mm", "계산 비아 안쪽 반경", " mm");
    Line(text, used, "thickness_mm", "계산 적층 두께", " mm");
    Line(text, used, "thickness_m", "계산 도체 두께", " m");
    text += "\n계획의 계산 입력 전체\n" + used.dump(2);
    return text;
}

std::string OriginalValues(const Json& data)
{
    const auto& original = data.at("original");
    const auto& parameters = data.at("parameters");
    std::string text;
    for (const auto& [key, label, unit] : {
             std::tuple{"resistance", "원본 급전 저항", " ohm"},
             std::tuple{"epsilon_r", "원본 상대 유전율", ""},
             std::tuple{"tan_delta", "원본 손실 탄젠트", ""},
             std::tuple{"conductivity", "원본 전도도", " S/m"},
             std::tuple{"thickness", "원본 적층 두께", " m"},
             std::tuple{"width", "원본 도체 폭", " m"}})
    {
        if (!original.contains(key))
        {
            continue;
        }
        const auto& value = original.at(key);
        const auto& quantity = value.contains("parameter_id")
            ? parameters.at(value.at("parameter_id").get<std::string>()).at("original").at("quantity") : value;
        Line(text, quantity, "value_si", label, quantity.at("value_si").is_null() ? "" : unit);
    }
    text += "\n봉인 설계에 저장된 값 (value_si는 SI 값)\n" + original.dump(2);
    if (!parameters.empty())
    {
        text += "\n\n참조 매개변수의 당시 값과 식\n" + parameters.dump(2);
    }
    if (data.contains("geometry_lineage"))
    {
        const auto& entry = data.at("geometry_lineage");
        const auto state = entry.at("current_state").get<std::string>();
        text += std::string("\n\n현재 설계와 비교: ") + (state == "removed" ? "삭제" : state == "edited" ? "편집됨" : "동일") + "\n";
        Line(text, entry, "current_revision_id", "현재 개정");
        Line(text, entry, "changed_fields", "변경된 속성");
        Line(text, entry, "original_sha256", "당시 도체 SHA-256");
        Line(text, entry, "precision_edits", "봉인 개정에 남은 정밀 편집");
        for (const auto& source : entry.at("imports"))
        {
            text += "\n제조 원문, 해시 및 대응 객체\n" + source.dump(2) + "\n";
        }
    }
    return text;
}

class EvidenceDialog final : public wxDialog
{
public:
    EvidenceDialog(wxWindow* parent, const std::string& artifact, DialogGateway gateway)
        : wxDialog(parent, wxID_ANY, Display("해석 입력과 출처"), wxDefaultPosition, wxDefaultSize,
                   wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
          m_gateway(std::move(gateway)), m_artifact(artifact)
    {
        SetName("solver.evidence");
        StudioTheme::ApplyTypography(*this);
        StudioTheme::BindSurface(*this);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        m_status = new wxStaticText(this, wxID_ANY, Display("결과의 봉인 개정과 해석 계획을 확인하고 있습니다."));
        m_status->SetName("solver.evidence.status");
        layout->Add(m_status, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
        m_tabs = new wxNotebook(this, wxID_ANY);
        BuildRevision();
        auto* conditions = new wxPanel(m_tabs);
        auto* conditionsLayout = new wxBoxSizer(wxVERTICAL);
        m_conditions = ReadOnly(conditions, "solver.evidence.conditions");
        conditionsLayout->Add(m_conditions, 1, wxEXPAND | wxALL, FromDIP(8));
        conditions->SetSizer(conditionsLayout);
        m_tabs->AddPage(conditions, Display("당시 해석 조건"));
        BuildObjects();
        layout->Add(m_tabs, 1, wxEXPAND | wxBOTTOM, FromDIP(8));
        auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
        StudioTheme::Button(*close);
        layout->Add(close, 0, wxALIGN_RIGHT);
        auto* outer = new wxBoxSizer(wxVERTICAL);
        outer->Add(layout, 1, wxEXPAND | wxALL, FromDIP(12));
        SetSizer(outer);
        SetMinClientSize(FromDIP(wxSize(590, 440)));
        SetClientSize(FromDIP(wxSize(760, 540)));
        CentreOnParent();
        m_tabs->Disable();
        Read({}, [this](const Json& result)
        {
            AcceptSummary(result);
        },
        [this](const Json& error)
        {
            m_status->SetLabel(Display(DiagnosticMessage(error)));
        });
    }

private:
    /** @brief 창이 닫힌 뒤 도착한 응답을 버리고 선택된 결과 ID를 모든 요청에 사용한다. */
    void Read(Json input, Callback success, Callback failure)
    {
        input["artifact_id"] = m_artifact;
        const wxWeakRef<EvidenceDialog> weak(this);
        m_gateway("result.solver_evidence", input, false,
                  [weak, success = std::move(success)](const Json& data)
                  {
                      if (weak)
                      {
                          success(data);
                      }
                  },
                  [weak, failure = std::move(failure)](const Json& error)
                  {
                      if (weak)
                      {
                          failure(error);
                      }
                  });
    }

    void BuildRevision()
    {
        auto* panel = new wxPanel(m_tabs);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        m_revision = ReadOnly(panel, "solver.evidence.revision");
        layout->Add(m_revision, 1, wxEXPAND | wxALL, FromDIP(8));
        m_openRevision = new wxButton(panel, wxID_ANY, Display("봉인 설계 원문 열기"));
        m_openRevision->SetName("solver.evidence.revision.open");
        StudioTheme::Button(*m_openRevision);
        layout->Add(m_openRevision, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        m_openRevision->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            m_openRevision->Disable();
            Read({{"page", "revision"}}, [this](const Json& data)
            {
                Present(m_revision, m_revisionSummary + "\n봉인 설계 원문 (JSON)\n" +
                        Json::parse(data.at("document_json").get<std::string>()).dump(2));
                m_revision->SetFocus();
            }, [this](const Json& error)
            {
                Present(m_revision, m_revisionSummary + "\n" + DiagnosticMessage(error));
                m_openRevision->Enable();
            });
        });
        panel->SetSizer(layout);
        m_tabs->AddPage(panel, Display("당시 설계"));
    }

    void BuildObjects()
    {
        auto* panel = new wxPanel(m_tabs);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        m_objectChoice = new wxChoice(panel, wxID_ANY);
        m_objectChoice->SetName("solver.evidence.object");
        layout->Add(m_objectChoice, 0, wxEXPAND | wxALL, FromDIP(8));
        auto* details = new wxNotebook(panel, wxID_ANY);
        m_used = ReadOnly(details, "solver.evidence.used");
        m_original = ReadOnly(details, "solver.evidence.original");
        details->AddPage(m_used, Display("계산 입력"));
        details->AddPage(m_original, Display("설계 원본 값"));
        auto* source = new wxPanel(details);
        auto* sourcesLayout = new wxBoxSizer(wxVERTICAL);
        m_sourceChoice = new wxChoice(source, wxID_ANY);
        m_sourceChoice->SetName("solver.evidence.source");
        sourcesLayout->Add(m_sourceChoice, 0, wxEXPAND | wxALL, FromDIP(6));
        m_source = ReadOnly(source, "solver.evidence.source.text");
        sourcesLayout->Add(m_source, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
        source->SetSizer(sourcesLayout);
        details->AddPage(source, Display("출처"));
        auto* history = new wxPanel(details);
        auto* historyLayout = new wxBoxSizer(wxVERTICAL);
        m_history = ReadOnly(history, "solver.evidence.history");
        historyLayout->Add(m_history, 1, wxEXPAND | wxALL, FromDIP(6));
        m_openHistory = new wxButton(history, wxID_ANY, Display("객체 편집 이력 읽기"));
        m_openHistory->SetName("solver.evidence.history.open");
        StudioTheme::Button(*m_openHistory);
        historyLayout->Add(m_openHistory, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
        m_openHistory->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            LoadHistory();
        });
        history->SetSizer(historyLayout);
        details->AddPage(history, Display("편집 이력"));
        layout->Add(details, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        panel->SetSizer(layout);
        m_tabs->AddPage(panel, Display("재료와 급전"));
        m_objectChoice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            LoadObject();
        });
        m_sourceChoice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            LoadSource();
        });
    }

    void AcceptSummary(const Json& data)
    {
        const auto& snapshot = data.at("snapshot");
        const auto& plan = data.at("plan");
        m_status->SetLabel(Display(data.at("current_revision_id") == data.at("revision_id")
                                      ? "조회 시점의 현재 개정과 같은 결과입니다."
                                      : "이전 설계에서 계산한 결과입니다. 아래에는 당시 값을 표시합니다."));
        m_revisionSummary = data.at("name").get<std::string>() + "\n" + data.at("description").get<std::string>() +
            "\n\n결과 ID  " + m_artifact + "\n"
            "당시 개정  " + data.at("revision_id").get<std::string>() + "\n"
            "조회 시점의 현재 개정  " + data.at("current_revision_id").get<std::string>() + "\n"
            "스냅샷 ID  " + snapshot.at("snapshot_id").get<std::string>() + "\n"
            "설계 SHA-256  " + snapshot.at("content_hash").get<std::string>() + "\n"
            "해석 계획 ID  " + plan.at("plan_id").get<std::string>() + "\n"
            "해석 계획 SHA-256  " + plan.at("content_hash").get<std::string>() + "\n";
        Present(m_revision, m_revisionSummary);
        const auto& settings = data.at("settings");
        std::string conditions;
        Line(conditions, settings.at("frequency_hz"), "start", "시작 주파수", " Hz");
        Line(conditions, settings.at("frequency_hz"), "stop", "끝 주파수", " Hz");
        Line(conditions, settings, "grid_mm", "모델 최대 격자 간격", " mm");
        Line(conditions, settings, "feature_subdivisions", "임계 구간 최소 분할");
        Line(conditions, settings, "max_timesteps", "최대 시간 단계");
        Line(conditions, settings, "end_criterion", "종료 에너지 비율");
        Present(m_conditions, conditions + "\n봉인 계획의 해석 조건 전체\n" + settings.dump(2));
        m_objects = data.at("objects");
        int first = 0;
        for (const auto& object : m_objects)
        {
            const auto kind = object.at("kind").get<std::string>();
            auto label = Kind(kind);
            if (kind == "terminal")
            {
                label = object.at("id") == data.at("terminals").at("positive_geometry_id")
                    ? "신호 단자 도체" : "기준 단자 도체";
            }
            const auto index = m_objectChoice->Append(Display(label + " / " + object.at("name").get<std::string>()));
            if (kind == "port")
            {
                first = index;
            }
        }
        m_objectChoice->SetSelection(first);
        m_tabs->Enable();
        LoadObject();
        Layout();
    }

    void LoadObject()
    {
        const int index = m_objectChoice->GetSelection();
        if (index == wxNOT_FOUND)
        {
            return;
        }
        const auto generation = ++m_objectGeneration;
        ++m_sourceGeneration;
        m_sourceChoice->Clear();
        m_sourceChoice->Disable();
        Present(m_used, "당시 계산 입력을 읽고 있습니다.");
        Present(m_original, "");
        Present(m_source, "");
        const auto& object = m_objects.at(index);
        const auto kind = object.at("kind").get<std::string>();
        const bool hasHistory = kind == "geometry" || kind == "terminal";
        m_historyOffset = 0;
        m_historyText.clear();
        m_openHistory->SetLabel(Display("객체 편집 이력 읽기"));
        m_openHistory->Enable(hasHistory);
        Present(m_history, hasHistory ? "이 결과를 계산할 때까지의 객체 편집을 조회합니다."
                                     : "도체 또는 급전 단자 도체를 선택하십시오.");
        Read({{"page", "object"}, {"kind", object.at("kind")}, {"id", object.at("id")}},
             [this, generation](const Json& data)
             {
                 if (generation != m_objectGeneration)
                 {
                     return;
                 }
                 Present(m_used, UsedValues(data));
                 Present(m_original, OriginalValues(data));
                 if (data.at("sources").empty())
                 {
                     Present(m_source, "이 입력의 봉인 원본에 출처 참조가 기록되지 않았습니다.");
                     return;
                 }
                 for (const auto& source : data.at("sources"))
                 {
                     const auto ref = Display(source.at("reference").get<std::string>());
                     const auto index = m_sourceChoice->GetCount() + 1;
                     m_sourceChoice->Append(wxString::Format("%u. ", index) + ref.Left(90));
                 }
                 m_sourceChoice->Enable();
                 m_sourceChoice->SetSelection(0);
                 LoadSource();
             },
             [this, generation](const Json& error)
             {
                 if (generation == m_objectGeneration)
                 {
                     const auto message = DiagnosticMessage(error);
                     Present(m_used, message);
                     Present(m_original, message);
                     Present(m_source, message);
                 }
             });
    }

    /** @brief 선택 결과의 봉인 개정에서 과거 방향으로 객체 편집을 읽는다. */
    void LoadHistory()
    {
        const auto generation = m_objectGeneration;
        const auto& object = m_objects.at(m_objectChoice->GetSelection());
        m_openHistory->Disable();
        Read({{"page", "history"}, {"kind", object.at("kind")}, {"id", object.at("id")}, {"offset", m_historyOffset}},
             [this, generation](const Json& data)
             {
                 if (generation != m_objectGeneration)
                 {
                     return;
                 }
                 for (const auto& row : data.at("rows"))
                 {
                     const auto action = row.at("action").get<std::string>();
                     m_historyText += action == "added" ? "객체 추가\n" : action == "removed" ? "객체 삭제\n" : "객체 편집\n";
                     Line(m_historyText, row, "revision_id", "개정");
                     Line(m_historyText, row, "parent_revision_id", "이전 개정");
                     Line(m_historyText, row, "command_type", "명령");
                     const auto& move = row.at("history_action");
                     if (!move.is_null())
                     {
                         m_historyText += move.at("direction") == "undo" ? "실행 취소\n" : "다시 실행\n";
                     }
                     Line(m_historyText, row, "fields", "변경 속성");
                     m_historyText += "변경 전\n" + row.at("before").dump(2) + "\n변경 후\n" +
                                      row.at("after").dump(2) + "\n\n";
                 }
                 std::string status;
                 if (data.at("status") == "continued")
                 {
                     m_historyOffset = data.at("next_offset").get<int>();
                     status = "이전 개정이 더 있습니다.";
                     m_openHistory->SetLabel(Display("이전 개정 더 읽기"));
                     m_openHistory->Enable();
                 }
                 else if (data.at("status") == "unavailable")
                 {
                     status = "이전 개정이 이 저장소에 없습니다.\n" + data.at("boundary_revision_id").get<std::string>();
                 }
                 else if (m_historyText.empty())
                 {
                     status = "보존된 개정에 객체 속성 편집이 없습니다.";
                 }
                 Present(m_history, m_historyText + status);
                 m_history->SetFocus();
             },
             [this, generation](const Json& error)
             {
                 if (generation == m_objectGeneration)
                 {
                     Present(m_history, m_historyText + DiagnosticMessage(error));
                     m_openHistory->Enable();
                 }
             });
    }

    void LoadSource()
    {
        const auto generation = ++m_sourceGeneration;
        const auto& object = m_objects.at(m_objectChoice->GetSelection());
        Present(m_source, "선택한 출처를 확인하고 있습니다.");
        Read({{"page", "source"}, {"kind", object.at("kind")}, {"id", object.at("id")},
              {"source_index", m_sourceChoice->GetSelection()}},
             [this, generation](const Json& data)
             {
                 if (generation != m_sourceGeneration)
                 {
                     return;
                 }
                 std::string text = "원래 출처 참조\n" + data.at("reference").get<std::string>() + "\n\n참조한 입력 필드\n";
                 for (const auto& field : data.at("fields"))
                 {
                     text += field.get<std::string>() + "\n";
                 }
                 if (!data.at("citations").empty())
                 {
                     text += "\n채택 근거와 원문 포인터\n" + data.at("citations").dump(2) + "\n";
                 }
                 const auto& record = data.at("record");
                 if (record.is_null())
                 {
                     text += "\n이 참조에 연결된 원문 사본은 봉인 설계에 없습니다.";
                 }
                 else
                 {
                     Json basis = record;
                     basis.erase("raw_json");
                     text += "\n원문 식별 정보 및 SHA-256\n" + basis.dump(2) +
                             "\n\n가져온 당시 원문\n" + record.at("raw_json").get<std::string>();
                 }
                 Present(m_source, text);
             },
             [this, generation](const Json& error)
             {
                 if (generation == m_sourceGeneration)
                 {
                     Present(m_source, DiagnosticMessage(error));
                 }
             });
    }

    DialogGateway m_gateway;
    std::string m_artifact;
    std::string m_revisionSummary;
    Json m_objects;
    unsigned m_objectGeneration = 0;
    unsigned m_sourceGeneration = 0;
    wxStaticText* m_status = nullptr;
    wxNotebook* m_tabs = nullptr;
    wxButton* m_openRevision = nullptr;
    wxTextCtrl* m_revision = nullptr;
    wxTextCtrl* m_conditions = nullptr;
    wxChoice* m_objectChoice = nullptr;
    wxChoice* m_sourceChoice = nullptr;
    wxTextCtrl* m_used = nullptr;
    wxTextCtrl* m_original = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxTextCtrl* m_history = nullptr;
    wxButton* m_openHistory = nullptr;
    int m_historyOffset = 0;
    std::string m_historyText;
};
}

void ShowSolverEvidence(wxWindow* parent, const std::string& artifact, DialogGateway gateway)
{
    EvidenceDialog dialog(parent, artifact, std::move(gateway));
    dialog.ShowModal();
}
