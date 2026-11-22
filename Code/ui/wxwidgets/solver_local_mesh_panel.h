/** @file @brief 객체별 국부 격자 편집과 실제 적용 구간 목록을 제공한다. */
#pragma once

#include <array>
#include <functional>
#include <nlohmann/json.hpp>
#include <wx/panel.h>

class wxButton;
class wxListCtrl;

class SolverLocalMeshPanel final : public wxPanel
{
public:
    /** @brief 현재 개정의 객체 목록을 보존하고 조건 변경 및 격자 위치 이동을 연결한다. */
    SolverLocalMeshPanel(wxWindow* parent, const nlohmann::json& targets, std::function<void()> changed,
                         std::function<void(int, const std::array<double, 2>&, long, bool)> locate);
    const nlohmann::json& Rules() const { return m_rules; }
    void LoadRules(const nlohmann::json& rules);
    void DisplayReport(const nlohmann::json& report);
    void FocusRule(const std::string& path);

private:
    void Edit(long index);
    void FillRules(long selected);
    void UpdateActions();
    wxString Label(const nlohmann::json& rule) const;

    nlohmann::json m_targets;
    nlohmann::json m_rules = nlohmann::json::array();
    nlohmann::json m_segments = nlohmann::json::array();
    std::function<void()> m_changed;
    wxListCtrl* m_list = nullptr;
    wxListCtrl* m_report = nullptr;
    wxButton* m_add = nullptr;
    wxButton* m_edit = nullptr;
    wxButton* m_remove = nullptr;
    wxButton* m_locate = nullptr;
};
