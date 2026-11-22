/** @file @brief 축별 격자 품질, 경고 구간 및 설정 복귀를 제공한다. */
#pragma once

#include "solver_mesh_quality.h"
#include <functional>
#include <wx/panel.h>

class wxButton;
class wxListCtrl;
class wxStaticText;
class wxTextCtrl;

class SolverMeshQualityPanel final : public wxPanel
{
public:
    using Locate = std::function<void(const Studio::MeshQuality::Report&, const Studio::MeshQuality::Finding&,
                                     const wxString&)>;
    SolverMeshQualityPanel(wxWindow* parent, Locate locate, std::function<void(const std::string&)> edit);
    /** @brief 현재 검토 결과가 바뀌었을 때만 실제 격자에서 품질을 새로 읽는다. */
    void DisplayMesh(const nlohmann::json* mesh, const nlohmann::json* settings = nullptr);

private:
    void UpdateSelection();
    const Studio::MeshQuality::Finding* Selection() const;

    Studio::MeshQuality::Report m_report;
    wxStaticText* m_intro = nullptr;
    wxListCtrl* m_axes = nullptr;
    wxListCtrl* m_findings = nullptr;
    wxTextCtrl* m_details = nullptr;
    wxButton* m_locate = nullptr;
    wxButton* m_edit = nullptr;
};
