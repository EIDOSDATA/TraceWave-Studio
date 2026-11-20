/** @file @brief 서비스 환산으로 표시 단위를 바꾸며 원래 수량 입력을 보존한다. */
#pragma once
#include "dialog_gateway.h"
#include <wx/weakref.h>
#include <memory>
#include <vector>
class wxWindow;
class wxChoice;
class wxTextCtrl;

class MeasurementQuantityGroup final : public std::enable_shared_from_this<MeasurementQuantityGroup>
{
public:
    struct Item
    {
        std::string path;
        wxTextCtrl* text = nullptr;
        Json value = nullptr;
        Json input = nullptr;
    };
    static std::shared_ptr<MeasurementQuantityGroup> Create(wxWindow* owner, wxChoice* unit, std::vector<Item> items,
                                                            DialogGateway gateway);
    Json Input(std::size_t index) const;
    bool Edited() const;
    bool Pending() const;
    std::function<void()> onEdited;
    std::function<void()> onState;
    std::function<void(const std::string&)> onStatus;

private:
    void Bind();
    void Convert();
    void ConvertNext(std::size_t index);
    void Finish(const std::string& error);
    wxWeakRef<wxWindow> m_owner;
    wxChoice* m_unit = nullptr;
    std::vector<Item> m_items;
    std::vector<std::string> m_display;
    DialogGateway m_gateway;
    std::string m_shownUnit, m_requestedUnit;
    bool m_edited = false, m_pending = false;
};
