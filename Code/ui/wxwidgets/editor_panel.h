#pragma once

#include <wx/wx.h>
#include <wx/scrolwin.h>
#include <wx/grid.h>
#include <wx/tglbtn.h>
#include <nlohmann/json.hpp>
#include "editor_presentation.h"

#include <map>
#include <functional>
#include <string>
#include <vector>
#include <array>

wxDECLARE_EVENT(wxEVT_RFAD_EDITOR_CHANGED, wxCommandEvent);

/** @brief 서비스가 제공한 필드 DTO만 표시하고 변경 입력을 수집한다. */
class EditorPanel final : public wxScrolledWindow
{
public:
    explicit EditorPanel(wxWindow* parent);
    void SetFields(const nlohmann::json& fields, const nlohmann::json& selection = nlohmann::json::object(),
                   const nlohmann::json& coordinateChoices = nlohmann::json::array());
    nlohmann::json Changes() const;
    bool IsDirty() const;
    void SetFieldValue(const std::string& key, const nlohmann::json& value);
    nlohmann::json FieldValue(const std::string& key) const;
    std::string ShowDiagnostic(const std::string& field, const std::string& message);
    bool IsFieldVisible(const std::string& key) const;
    const std::string& DiagnosticField() const;
    const std::string& InputNotice() const;
    void EditCoordinateCellForSmoke(const std::string& key, int point, int axis, const std::string& value);

private:
    friend class StudioSmokeDriver;
    struct Field
    {
        nlohmann::json descriptor;
        wxWindow* control = nullptr;
        std::vector<wxWindow*> auxiliaries;
        wxPanel* row = nullptr;
        wxSizer* section = nullptr;
        wxStaticText* label = nullptr;
        wxBoxSizer* inputs = nullptr;
        nlohmann::json coordinateValue = nlohmann::json::array();
        wxString compactCoordinate = wxEmptyString;
        bool showingCompactCoordinate = false;
        int group = 0;
    };

    nlohmann::json ReadValue(const Field& field) const;
    void WriteValue(Field& field, const nlohmann::json& value);
    void EditCoordinates(const std::string& key, const std::function<void(wxGrid&, wxDialog&)>& opened = {});
    void UpdateModes();
    /** @brief 좁은 속성 창에서는 설명을 위로 옮기고 값/단위 행의 폭을 확보한다. */
    void ReflowRows(bool force = false);
    void NotifyChanged();
    void UpdateInputNotice();
    EditorPresentation::Fields PresentationFields() const;
    std::string ResolveDiagnosticField(const std::string& path) const;
    std::map<std::string, Field> m_fields;
    nlohmann::json m_selection = nlohmann::json::object();
    nlohmann::json m_coordinateChoices = nlohmann::json::array();
    wxBoxSizer* m_layout = nullptr;
    wxStaticText* m_diagnostic = nullptr;
    wxStaticText* m_inputNotice = nullptr;
    wxToggleButton* m_details = nullptr;
    struct Group
    {
        wxToggleButton* header = nullptr;
        wxBoxSizer* rows = nullptr;
    };
    std::array<Group, 4> m_groups{};
    wxStaticText* m_valueState = nullptr;
    std::string m_diagnosticField;
    std::string m_inputNoticeText;
    bool m_notifying = false;
    bool m_compactRows = true;
    bool m_reflowing = false;
};
