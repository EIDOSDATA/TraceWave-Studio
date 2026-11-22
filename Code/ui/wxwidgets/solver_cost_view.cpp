/** @file @brief 같은 단위의 예상 및 실제 사용량과 실행 종료 사유를 표시한다. */
#include "solver_cost_view.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <array>
#include <tuple>
#include <vector>
#include <wx/listctrl.h>
#include <wx/wx.h>

namespace
{
wxString Time(double seconds)
{
    return seconds >= 60 ? wxString::Format(Display("%.0f초 (%.1f분)"), seconds, seconds / 60)
                         : wxString::Format(Display("%.2f초"), seconds);
}

wxString Bytes(double bytes)
{
    constexpr double KiB = 1024.0;
    constexpr double MiB = KiB * KiB;
    return bytes >= MiB ? wxString::Format("%.2f MiB", bytes / MiB)
                        : wxString::Format("%.2f KiB", bytes / KiB);
}

wxString TimeRange(const Json& estimate)
{
    const double low = estimate.at("wall_seconds_low");
    const double high = estimate.at("wall_seconds_high");
    return low >= 60 ? wxString::Format(Display("%.1f ~ %.1f분"), low / 60, high / 60)
                     : wxString::Format(Display("%.2f ~ %.2f초"), low, high);
}

wxString Reason(const Json& end)
{
    const std::string reason = end.at("reason");
    if (reason == "end_criterion_reached")
    {
        return Display("에너지 종료 기준 도달");
    }
    if (reason == "timestep_limit")
    {
        return Display("최대 시간 단계 도달");
    }
    if (reason == "timeout")
    {
        return Display("실행 시간 한도 도달");
    }
    if (reason == "output_limit")
    {
        return Display("출력 용량 한도 도달");
    }
    if (reason == "cancelled")
    {
        return Display("사용자가 취소함");
    }
    if (reason == "interrupted")
    {
        return Display("실행 중단");
    }
    return Display("해석 오류");
}

wxString TerminationText(const Json& end, const Json& estimate)
{
    wxString text = Reason(end);
    if (!end.value("confirmed", false))
    {
        text += Display(" / 프로세스 종료 확인 대기");
    }
    if (end.value("iterations", Json()).is_number())
    {
        text += Display(" / 시간 단계 ") + Display(end.at("iterations").dump()) +
                " / " + Display(estimate.at("max_timesteps").dump());
    }
    if (end.value("target_energy_ratio", Json()).is_number())
    {
        text += wxString::Format(Display("\n목표 에너지 비율 %.6g"), end.at("target_energy_ratio").get<double>());
        if (end.value("decay_db", Json()).is_number())
        {
            text += wxString::Format(Display(" / 실제 감쇠 %.4g dB"), end.at("decay_db").get<double>());
        }
        else if (end.value("zero_energy", false))
        {
            text += Display(" / 보고된 에너지 0");
        }
    }
    const auto message = end.value("message", std::string());
    if (!message.empty() && end.at("reason") == "solver_error")
    {
        text += "\n" + Display(message);
    }
    return text;
}

void DisplayRows(wxListCtrl& table, const Json& estimate, const Json& actual)
{
    table.DeleteAllItems();
    const auto add = [&](const char* label, const wxString& expected, const wxString& observed, const wxString& change)
    {
        const auto index = table.InsertItem(table.GetItemCount(), Display(label));
        table.SetItem(index, 1, expected);
        table.SetItem(index, 2, observed);
        table.SetItem(index, 3, change);
    };
    const auto delta = [](double observed, double expected)
    {
        return wxString::Format("%+.1f%%", (observed / expected - 1) * 100);
    };
    const auto elapsed = actual.value("wall_seconds", Json());
    wxString elapsedChange = "-";
    if (elapsed.is_number())
    {
        const double seconds = elapsed;
        elapsedChange = seconds < estimate.at("wall_seconds_low").get<double>() ? Display("예상보다 짧음")
                      : seconds > estimate.at("wall_seconds_high").get<double>() ? Display("예상보다 길음")
                      : Display("예상 범위 내");
    }
    add("openEMS 실행 시간", TimeRange(estimate),
        elapsed.is_number() ? Time(elapsed) : Display("미계측"), elapsedChange);
    const double memoryEstimate = estimate.at("memory_bytes");
    const auto memory = actual.value("peak_rss_bytes", Json());
    add("메모리 / 피크 RSS", Bytes(memoryEstimate),
        memory.is_number() ? Bytes(memory) : Display("미계측"),
        memory.is_number() ? delta(memory, memoryEstimate) : wxString("-"));
    const double rawEstimate = estimate.at("raw_output_bytes");
    const auto output = actual.value("raw_output_bytes", Json());
    add("원시 출력 용량", Bytes(rawEstimate), output.is_number() ? Bytes(output) : Display("미계측"),
        output.is_number() ? (actual.value("partial_raw", false) ? Display("부분 기록") : delta(output, rawEstimate)) : wxString("-"));
}
}

wxString Studio::SolverEstimateText(const Json& estimate)
{
    if (estimate.empty())
    {
        return {};
    }
    return Display("예상 실행 비용\nopenEMS 시간 ") + TimeRange(estimate) +
        Display(" (최대 시간 단계 기준)\n메모리 ") + Bytes(estimate.at("memory_bytes")) +
        Display(" / 원시 출력 ") + Bytes(estimate.at("raw_output_bytes")) +
        Display("\n계획 허용 한도 ") + Time(estimate.at("plan_wall_limit_seconds")) + " / " +
        Bytes(estimate.at("package_limit_bytes")) +
        Display("\n참조 처리율을 적용한 초기 추정입니다. 실제 에너지 종료 시점과 PC 부하에 따라 달라집니다.");
}

void Studio::ShowSolverCost(wxWindow* parent, const Json& completed, const Json& lastAttempt, bool preferAttempt)
{
    wxDialog dialog(parent, wxID_ANY, Display("실행 비용과 종료"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("solver.cost.dialog");
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    const int gap = dialog.FromDIP(StudioTheme::InputGap);
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* source = new wxChoice(&dialog, wxID_ANY);
    source->SetName("solver.cost.source");
    std::vector<Json> records;
    if (!completed.empty())
    {
        source->Append(Display("완료 결과"));
        records.push_back(completed);
    }
    if (!lastAttempt.empty())
    {
        source->Append(Display("최근 미완료 시도"));
        records.push_back(lastAttempt);
    }
    source->SetSelection(preferAttempt ? static_cast<int>(records.size()) - 1 : 0);
    root->Add(source, 0, wxEXPAND | wxALL, gap);
    auto* reason = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
    reason->SetName("solver.cost.termination");
    StudioTheme::Heading(*reason);
    root->Add(reason, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    auto* table = new wxListCtrl(&dialog, wxID_ANY, wxDefaultPosition, dialog.FromDIP(wxSize(-1, 140)), wxLC_REPORT);
    table->SetName("solver.cost.comparison");
    StudioTheme::Table(*table);
    table->AppendColumn(Display("항목"), wxLIST_FORMAT_LEFT, dialog.FromDIP(172));
    table->AppendColumn(Display("예상"), wxLIST_FORMAT_RIGHT, dialog.FromDIP(235));
    table->AppendColumn(Display("실제"), wxLIST_FORMAT_RIGHT, dialog.FromDIP(137));
    table->AppendColumn(Display("비교"), wxLIST_FORMAT_LEFT, dialog.FromDIP(135));
    root->Add(table, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    auto* details = new wxTextCtrl(&dialog, wxID_ANY, wxEmptyString, wxDefaultPosition, dialog.FromDIP(wxSize(-1, 136)),
                                   wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    details->SetName("solver.cost.details");
    root->Add(details, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    auto* close = new wxButton(&dialog, wxID_CANCEL, Display("닫기"));
    StudioTheme::Button(*close);
    root->Add(close, 0, wxALIGN_RIGHT | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    dialog.SetSizer(root);

    const auto refresh = [&]()
    {
        const auto& report = records.at(source->GetSelection());
        const auto& estimate = report.at("estimate");
        const auto& actual = report.at("actual");
        reason->SetLabel(TerminationText(report.at("termination"), estimate));
        reason->Wrap(dialog.FromDIP(680));
        DisplayRows(*table, estimate, actual);
        wxString common = Display("예상 시간은 최대 시간 단계와 참조 처리율을 사용합니다. 실제 메모리는 openEMS의 최대 RSS입니다.");
        if (report.value("estimate_retrospective", false))
        {
            common += Display("\n과거 결과의 예상치는 당시 실행 계획에서 다시 계산했습니다.");
        }
        const auto scope = report.value("execution_budget_seconds", Json());
        if (scope.is_number())
        {
            common += Display("\n실행에 요청한 시간 한도 ") + Time(scope);
        }
        static constexpr std::array<std::tuple<const char*, const char*, bool>, 4> measurements{{
            {"postprocess_seconds", "후처리 시간", true}, {"archived_output_bytes", "전체 보존 결과", false},
            {"worker_wall_seconds", "WSL 작업 관측 시간", true}, {"observed_output_peak_bytes", "WSL 작업 출력 관측 최대", false}}};
        for (const auto& [key, label, isTime] : measurements)
        {
            const auto value = actual.value(key, Json());
            if (value.is_number())
            {
                common += "\n" + Display(label) + " " + (isTime ? Time(value) : Bytes(value));
            }
        }
        common += Display("\n해석 개정 ") + Display(report.at("revision_id").get<std::string>());
        const auto recovery = report.value("recovery_stage", std::string());
        if (recovery == "restart_prepared_plan")
        {
            common += Display("\n복구 가능 단계: 보존한 입력으로 처음부터 다시 실행할 수 있습니다.");
        }
        else if (recovery == "confirm_guest_exit")
        {
            common += Display("\n복구 가능 단계: WSL 프로세스 종료를 먼저 확인해야 합니다.");
        }
        const auto energy = report.value("energy_observations", Json::object());
        if (!energy.empty())
        {
            const auto& samples = energy.at("samples");
            common += wxString::Format(Display("\n\n에너지 감쇠 기록 %zu / %zu개 (로그 기록 간격)"),
                samples.size(), energy.at("logged_total").get<std::size_t>());
            for (const auto& sample : samples)
            {
                const auto decay = sample.value("decay_db", Json());
                common += "\n" + Display(sample.at("step").dump()) + Display(" 단계  ");
                if (decay.is_number())
                {
                    common += wxString::Format("%.4g dB", decay.get<double>());
                }
                else
                {
                    common += Display("유한한 감쇠값 없음");
                }
                if (sample.at("final").get<bool>())
                {
                    common += Display("  (종료 확인)");
                }
            }
        }
        details->ChangeValue(common);
        dialog.Layout();
    };
    source->Bind(wxEVT_CHOICE, [&](wxCommandEvent&) { refresh(); });
    dialog.SetMinSize(dialog.FromDIP(wxSize(708, 394)));
    dialog.SetSize(dialog.FromDIP(wxSize(794, 462)));
    refresh();
    dialog.CentreOnParent();
    dialog.ShowModal();
}
