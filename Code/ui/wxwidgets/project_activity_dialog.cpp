/** @file @brief 개정과 객체 검색 및 기록별 고정 원본 이동을 제공한다. */
#include "project_activity_dialog.h"
#include "solver_evidence_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/listctrl.h>
#include <wx/weakref.h>
#include <wx/wx.h>
#include <algorithm>
#include <array>
#include <utility>
#include <ctime>

namespace
{
using Callback = std::function<void(const Json&)>;

std::string Kind(const std::string& kind)
{
    if (kind == "condition")
    {
        return "저장 조건";
    }
    if (kind == "plan")
    {
        return "계획 조건";
    }
    if (kind == "prepare")
    {
        return "해석 준비";
    }
    if (kind == "run" || kind == "result")
    {
        return "해석 실행";
    }
    if (kind == "study_report")
    {
        return "수렴 보고서";
    }
    if (kind == "rf_report")
    {
        return "RF 검증 보고서";
    }
    return "인계 보고서";
}

std::string State(const std::string& state)
{
    const std::array<std::pair<const char*, const char*>, 8> labels{std::pair{"recorded", "보존"}, {"completed", "완료"}, {"failed", "실패"},
                            {"running", "실행 중"}, {"queued", "대기 중"}, {"cancelled", "취소"},
                            {"interrupted", "중단"}, {"partial_evidence", "부분 근거"}};
    const auto label = std::find_if(labels.begin(), labels.end(), [&state](const auto& entry)
    {
        return state == entry.first;
    });
    return label == labels.end() ? state : label->second;
}

/** @brief 검색 세대, 행 선택과 원본 이동의 응답을 분리해 늦은 조회를 버린다. */
class ActivityDialog final : public wxDialog
{
public:
    ActivityDialog(wxWindow* parent, const std::string& revision, const std::string& object, DialogGateway gateway)
        : wxDialog(parent, wxID_ANY, Display("프로젝트 기록 찾기"), wxDefaultPosition, wxDefaultSize,
                   wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
          m_gateway(std::move(gateway)), m_currentRevision(revision)
    {
        SetName("project.activity");
        StudioTheme::ApplyTypography(*this);
        StudioTheme::BindSurface(*this);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        auto* filters = new wxFlexGridSizer(2, FromDIP(6), FromDIP(8));
        filters->AddGrowableCol(1, 1);
        m_revision = AddFilter(filters, "개정 / 스냅샷 ID", "project.activity.revision", "");
        m_revision->SetToolTip(Display("개정 또는 스냅샷의 전체 ID나 앞부분을 입력하세요."));
        m_object = AddFilter(filters, "객체 이름 / ID", "project.activity.object", object);
        filters->Add(new wxStaticText(this, wxID_ANY, Display("기록 종류")), 0, wxALIGN_CENTER_VERTICAL);
        m_category = new wxChoice(this, wxID_ANY);
        m_category->SetName("project.activity.category");
        for (const auto* label : {"모든 기록", "해석 조건", "실행 기록", "보고서"})
        {
            m_category->Append(Display(label));
        }
        m_category->SetSelection(0);
        filters->Add(m_category, 1, wxEXPAND);
        layout->Add(filters, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
        auto* search = new wxBoxSizer(wxHORIZONTAL);
        Button(search, "검색", "project.activity.search", [this]()
        {
            Search(0);
        });
        Button(search, "현재 개정으로 검색", "project.activity.current", [this]()
        {
            m_revision->ChangeValue(Display(m_currentRevision));
            Search(0);
        });
        m_previous = Button(search, "이전", "project.activity.previous", [this]()
        {
            Search(std::max(0, m_catalog.at("offset").get<int>() - PageSize));
        });
        m_next = Button(search, "다음", "project.activity.next", [this]()
        {
            Search(m_catalog.at("next_offset").get<int>());
        });
        layout->Add(search, 0, wxEXPAND | wxBOTTOM, FromDIP(6));

        m_status = new wxStaticText(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                                    wxST_NO_AUTORESIZE | wxST_ELLIPSIZE_END);
        m_status->SetName("project.activity.status");
        StudioTheme::BindSecondary(*m_status);
        layout->Add(m_status, 0, wxEXPAND | wxBOTTOM, FromDIP(6));

        m_list = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 160)),
                                wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
        m_list->SetName("project.activity.items");
        StudioTheme::Table(*m_list);
        for (const auto& column : {std::pair{"종류", 118}, {"기록", 196}, {"당시 개정", 88},
                                  {"상태", 66}, {"일치한 객체", 151}, {"기록 시각", 164}})
        {
            m_list->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
        }
        layout->Add(m_list, 3, wxEXPAND | wxBOTTOM, FromDIP(8));

        m_detail = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 142)),
                                  wxTE_MULTILINE | wxTE_READONLY);
        m_detail->SetName("project.activity.detail");
        layout->Add(m_detail, 4, wxEXPAND | wxBOTTOM, FromDIP(8));
        m_links = new wxChoice(this, wxID_ANY);
        m_links->SetName("project.activity.links");
        layout->Add(m_links, 0, wxEXPAND | wxBOTTOM, FromDIP(6));
        auto* actions = new wxBoxSizer(wxHORIZONTAL);
        m_result = Button(actions, "결과 열기", "project.activity.result.open", [this]()
        {
            OpenResult(false);
        });
        m_evidence = Button(actions, "해석 입력과 출처", "project.activity.evidence.open", [this]()
        {
            OpenResult(true);
        });
        m_origin = Button(actions, "당시 설계 열기", "project.activity.origin.open", [this]()
        {
            Origin();
        });
        m_back = Button(actions, "기록 내용", "project.activity.detail.open", [this]()
        {
            ++m_actionGeneration;
            Present(DetailText());
            Actions();
        });
        actions->AddStretchSpacer();
        auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
        StudioTheme::Button(*close);
        actions->Add(close, 0);
        layout->Add(actions, 0, wxEXPAND);

        auto* outer = new wxBoxSizer(wxVERTICAL);
        outer->Add(layout, 1, wxEXPAND | wxALL, FromDIP(12));
        SetSizer(outer);
        SetMinClientSize(FromDIP(wxSize(660, 520)));
        SetClientSize(FromDIP(wxSize(840, 626)));
        CentreOnParent();

        const auto filterChanged = [this](wxCommandEvent&)
        {
            ++m_searchGeneration;
            m_catalog = nullptr;
            m_list->DeleteAllItems();
            m_previous->Disable();
            m_next->Disable();
            ClearSelection("");
            Status("검색을 누르면 입력한 범위의 기록을 조회합니다.");
        };
        m_revision->Bind(wxEVT_TEXT, filterChanged);
        m_object->Bind(wxEVT_TEXT, filterChanged);
        m_category->Bind(wxEVT_CHOICE, filterChanged);
        m_list->Bind(wxEVT_LIST_ITEM_SELECTED, [this](wxListEvent& event)
        {
            Select(event.GetIndex());
        });
        m_list->Bind(wxEVT_LIST_ITEM_ACTIVATED, [this](wxListEvent&)
        {
            m_detail->SetFocus();
        });
        m_links->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            ++m_actionGeneration;
            Actions();
        });
        Search(0);
        (object.empty() ? m_object : m_revision)->SetFocus();
    }

    Json Chosen() const
    {
        return m_resultIdentity;
    }

private:
    static constexpr int PageSize = 20;

    wxTextCtrl* AddFilter(wxFlexGridSizer* sizer, const char* caption, const char* name, const std::string& value)
    {
        sizer->Add(new wxStaticText(this, wxID_ANY, Display(caption)), 0, wxALIGN_CENTER_VERTICAL);
        auto* text = new wxTextCtrl(this, wxID_ANY, Display(value), wxDefaultPosition, wxDefaultSize, wxTE_PROCESS_ENTER);
        text->SetName(name);
        text->SetMaxLength(256);
        sizer->Add(text, 1, wxEXPAND);
        text->Bind(wxEVT_TEXT_ENTER, [this](wxCommandEvent&)
        {
            Search(0);
        });
        return text;
    }

    wxButton* Button(wxBoxSizer* layout, const char* label, const char* name, std::function<void()> action)
    {
        auto* button = new wxButton(this, wxID_ANY, Display(label));
        button->SetName(name);
        StudioTheme::Button(*button);
        button->Bind(wxEVT_BUTTON, [action = std::move(action)](wxCommandEvent&)
        {
            action();
        });
        layout->Add(button, 0, wxRIGHT, FromDIP(6));
        return button;
    }

    void Read(const Json& input, Callback success, Callback failure)
    {
        const wxWeakRef<ActivityDialog> weak(this);
        m_gateway("result.project_activity", input, false,
                  [weak, success = std::move(success)](const Json& value)
                  {
                      if (weak)
                      {
                          success(value);
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

    void Status(const std::string& value)
    {
        const auto text = Display(value);
        m_status->SetLabel(text);
        m_status->SetToolTip(text);
    }

    void Present(const std::string& value)
    {
        m_detail->ChangeValue(Display(value));
        m_detail->ShowPosition(0);
    }

    void Actions()
    {
        const int index = m_links->GetSelection();
        const bool known = m_details.is_object();
        m_links->Enable(index != wxNOT_FOUND);
        m_result->Enable(index != wxNOT_FOUND);
        m_evidence->Enable(index != wxNOT_FOUND && m_details.at("links").at(index).at("has_evidence").get<bool>());
        m_origin->Enable(known);
        m_back->Enable(known);
    }

    void ClearSelection(const std::string& message)
    {
        ++m_selectionGeneration;
        ++m_actionGeneration;
        m_details = nullptr;
        m_selected = nullptr;
        m_links->Clear();
        Actions();
        Present(message);
    }

    void Search(int offset)
    {
        const std::array categories{"all", "settings", "run", "report"};
        if (offset == 0)
        {
            m_query = {{"page", "search"}, {"category", categories.at(m_category->GetSelection())},
                       {"revision", m_revision->GetValue().utf8_string()}, {"object", m_object->GetValue().utf8_string()},
                       {"limit", PageSize}, {"catalog_hash", nullptr}};
        }
        else
        {
            m_query["catalog_hash"] = m_catalog.at("catalog_hash");
        }
        m_query["offset"] = offset;
        const auto generation = ++m_searchGeneration;
        m_catalog = nullptr;
        m_list->DeleteAllItems();
        m_previous->Disable();
        m_next->Disable();
        ClearSelection("");
        Status("보존 개정의 기록을 찾고 있습니다.");
        Read(m_query, [this, generation](const Json& data)
        {
            if (generation == m_searchGeneration)
            {
                ShowPage(data);
            }
        }, [this, generation](const Json& error)
        {
            if (generation == m_searchGeneration)
            {
                Status("검색 실패 / " + DiagnosticMessage(error));
            }
        });
    }

    void ShowPage(const Json& data)
    {
        m_currentRevision = data.at("current_revision_id").get<std::string>();
        m_catalog = data;
        const auto& items = data.at("items");
        for (const auto& row : items)
        {
            const long index = m_list->InsertItem(m_list->GetItemCount(), Display(Kind(row.at("kind"))));
            m_list->SetItem(index, 1, Display(row.at("name")));
            m_list->SetItem(index, 2, Display(row.at("revision_id").get<std::string>().substr(0, 8)));
            m_list->SetItem(index, 3, Display(State(row.at("state"))));
            wxString matches;
            for (const auto& match : row.at("matches"))
            {
                if (!matches.empty())
                {
                    matches += ", ";
                }
                matches += Display(match.at("name"));
            }
            if (row.at("match_count").get<std::size_t>() > row.at("matches").size())
            {
                matches += Display(" 외 " + std::to_string(row.at("match_count").get<std::size_t>() - row.at("matches").size()));
            }
            m_list->SetItem(index, 4, matches);
            if (row.at("time").is_number())
            {
                const wxDateTime time(static_cast<std::time_t>(row.at("time").get<double>()));
                if (time.IsValid())
                {
                    m_list->SetItem(index, 5, time.FormatISOCombined(' '));
                }
            }
        }
        const int first = data.at("offset");
        m_previous->Enable(first > 0);
        m_next->Enable(!data.at("next_offset").is_null());
        Status(items.empty() ? "검색 범위에 보존된 기록이 없습니다."
               : std::to_string(first + 1) + "-" + std::to_string(first + items.size()) + " / "
                     + std::to_string(data.at("total").get<int>()) + "개");
        if (!items.empty())
        {
            Present("목록에서 기록을 선택하세요.");
        }
    }

    Json Request(const char* page) const
    {
        return {{"page", page}, {"kind", m_selected.at("kind")}, {"id", m_selected.at("id")}};
    }

    void Select(long index)
    {
        if (!m_catalog.is_object() || index < 0 || static_cast<std::size_t>(index) >= m_catalog.at("items").size())
        {
            return;
        }
        ClearSelection("선택한 기록을 확인하고 있습니다.");
        m_selected = m_catalog.at("items").at(index);
        const auto generation = m_selectionGeneration;
        Read(Request("detail"), [this, generation](const Json& data)
        {
            if (generation != m_selectionGeneration)
            {
                return;
            }
            m_details = data;
            for (const auto& link : data.at("links"))
            {
                m_links->Append(Display(link.at("name")));
            }
            if (!m_links->IsEmpty())
            {
                m_links->SetSelection(0);
            }
            Present(DetailText());
            Actions();
        }, [this, generation](const Json& error)
        {
            if (generation == m_selectionGeneration)
            {
                Present(DiagnosticMessage(error));
            }
        });
    }

    std::string DetailText() const
    {
        const auto& row = m_details.at("row");
        std::string text = Kind(row.at("kind")) + " / " + row.at("name").get<std::string>() + "\n" +
            "기록 ID  " + row.at("id").get<std::string>() + "\n" +
            "당시 개정  " + row.at("revision_id").get<std::string>() + "\n";
        if (row.at("snapshot_id").is_string())
        {
            text += "스냅샷 ID  " + row.at("snapshot_id").get<std::string>() + "\n";
        }
        if (row.at("record_revision_id").is_string())
        {
            text += "조건을 저장한 개정  " + row.at("record_revision_id").get<std::string>() + "\n";
        }
        const auto& body = m_details.at("body");
        text += "상태  " + State(row.at("state")) + "\n";
        const auto settings = body.value("settings", Json(nullptr));
        if (settings.is_object() && settings.contains("frequency_hz"))
        {
            const auto& band = settings.at("frequency_hz");
            const auto startGHz = Json(band.at("start").get<double>() / 1e9).dump();
            const auto stopGHz = Json(band.at("stop").get<double>() / 1e9).dump();
            text += "해석 대역  " + startGHz + " - " + stopGHz + " GHz    최대 시간 단계  " +
                    settings.at("max_timesteps").dump() + "\n";
        }
        if (body.contains("error") && body.at("error").is_object())
        {
            text += DiagnosticMessage(body.at("error")) + "\n";
        }
        if (m_details.at("links").empty())
        {
            text += "연결된 완료 결과가 없습니다.\n";
        }
        else if (m_details.at("relation") == "same_saved_settings")
        {
            text += "같은 저장 조건과 수치 설정을 확인한 결과입니다.\n";
        }
        return text + "\n기록 내용\n" + body.dump(2);
    }

    void Origin()
    {
        const auto generation = ++m_actionGeneration;
        Present("당시 개정을 해시로 확인하고 있습니다.");
        Read(Request("origin"), [this, generation](const Json& data)
        {
            if (generation != m_actionGeneration)
            {
                return;
            }
            std::string text = "당시 설계  " + data.at("metadata").at("name").get<std::string>() + "\n"
                "개정  " + data.at("row").at("revision_id").get<std::string>() + "\n"
                "설계 SHA-256  " + data.at("sha256").get<std::string>() + "\n\n";
            const auto& document = data.at("document");
            Present(text + (document.is_null() ? "대형 설계의 보존 정보\n" + data.at("metadata").dump(2) : document.dump(2)));
        }, [this, generation](const Json& error)
        {
            if (generation == m_actionGeneration)
            {
                Present(DiagnosticMessage(error));
            }
        });
    }

    void OpenResult(bool evidence)
    {
        auto input = Request("pin");
        input["artifact_id"] = m_details.at("links").at(m_links->GetSelection()).at("artifact_id");
        const auto generation = ++m_actionGeneration;
        m_result->Disable();
        m_evidence->Disable();
        Read(input, [this, generation, evidence](const Json& data)
        {
            if (generation != m_actionGeneration)
            {
                return;
            }
            Actions();
            if (evidence)
            {
                CallAfter([this, generation, identity = data.at("source").at("artifact_id").get<std::string>()]()
                {
                    if (IsModal() && generation == m_actionGeneration)
                    {
                        ShowSolverEvidence(this, identity, m_gateway);
                    }
                });
                return;
            }
            m_resultIdentity = data;
            EndModal(wxID_OK);
        }, [this, generation](const Json& error)
        {
            if (generation == m_actionGeneration)
            {
                Actions();
                Present(DiagnosticMessage(error));
            }
        });
    }

    DialogGateway m_gateway;
    std::string m_currentRevision;
    Json m_query, m_catalog, m_selected, m_details, m_resultIdentity;
    unsigned m_searchGeneration = 0, m_selectionGeneration = 0, m_actionGeneration = 0;
    wxTextCtrl* m_revision = nullptr;
    wxTextCtrl* m_object = nullptr;
    wxTextCtrl* m_detail = nullptr;
    wxChoice* m_category = nullptr;
    wxChoice* m_links = nullptr;
    wxListCtrl* m_list = nullptr;
    wxStaticText* m_status = nullptr;
    wxButton *m_previous = nullptr, *m_next = nullptr, *m_result = nullptr, *m_evidence = nullptr,
             *m_origin = nullptr, *m_back = nullptr;
};
}

Json ShowProjectActivity(wxWindow* parent, const std::string& revision, const std::string& object, DialogGateway gateway)
{
    ActivityDialog dialog(parent, revision, object, std::move(gateway));
    return dialog.ShowModal() == wxID_OK ? dialog.Chosen() : Json(nullptr);
}
