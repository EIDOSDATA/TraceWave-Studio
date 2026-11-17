/** @file @brief PCB 입력을 값/단위/참조와 명시 목록으로 편집하는 네이티브 폼이다. */
#pragma once
#include "dialog_gateway.h"
#include <wx/scrolwin.h>
#include <map>
#include <memory>

class wxBoxSizer;
class wxChoice;
class wxTextCtrl;
class wxCheckBox;
class wxCheckListBox;
class wxButton;

/** @brief 원문을 기본값으로 보존하고 사용자가 바꾼 허용 필드만 교체한다. */
class PcbFeatureForm final : public wxScrolledWindow
{
public:
    PcbFeatureForm(wxWindow* parent, DialogGateway gateway);
    void SetForm(const Json& form, const Json& context);
    void SetOperation(const std::string& operation, const std::string& section);
    Json Record() const;
    bool Dirty() const;
    bool Pending() const;
    bool Supported() const;
    std::function<void()> onChanged;
    std::function<void(const std::string&)> onStatus;
    std::function<void()> onStateChanged;

private:
    friend class StudioSmokeDriver;
    struct Field
    {
        Json descriptor;
        Json original;
        Json value;
        Json quantity;
        Json choices = Json::array();
        bool changed = false;
        bool loading = false;
        wxWindow* row = nullptr;
        wxTextCtrl* text = nullptr;
        wxChoice* choice = nullptr;
        wxChoice* unit = nullptr;
        wxChoice* mode = nullptr;
        wxChoice* parameter = nullptr;
        wxCheckBox* known = nullptr;
        wxCheckBox* check = nullptr;
        wxCheckListBox* checks = nullptr;
        wxButton* edit = nullptr;
        std::string shownUnit;
    };
    void BuildScalar(const std::shared_ptr<Field>& field, wxBoxSizer* row);
    void BuildSimple(const std::shared_ptr<Field>& field, wxBoxSizer* row);
    void BuildList(const std::shared_ptr<Field>& field, wxBoxSizer* row);
    void EditList(const std::shared_ptr<Field>& field);
    void ReadScalar(const std::shared_ptr<Field>& field);
    void ChangeUnit(const std::shared_ptr<Field>& field);
    void Changed(const std::shared_ptr<Field>& field, const Json& value);
    void StateChanged();
    Json m_form;
    Json m_context;
    DialogGateway m_gateway;
    wxBoxSizer* m_layout = nullptr;
    std::vector<std::shared_ptr<Field>> m_fields;
    std::uint64_t m_generation = 0;
    int m_pending = 0;
    bool m_supported = true;
};
