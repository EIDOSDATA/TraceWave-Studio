/** @file @brief 단위 변경은 표시만 바꾸고 수량 원문과 검토 입력을 유지한다. */
#include "measurement_quantity_group.h"
#include "studio_support.h"
#include <wx/choice.h>
#include <wx/textctrl.h>
#include <wx/window.h>
#include <iomanip>
#include <sstream>

std::shared_ptr<MeasurementQuantityGroup>
MeasurementQuantityGroup::Create(wxWindow* owner, wxChoice* unit, std::vector<Item> items, DialogGateway gateway)
{
    auto group = std::shared_ptr<MeasurementQuantityGroup>(new MeasurementQuantityGroup());
    group->m_owner = owner;
    group->m_unit = unit;
    group->m_items = std::move(items);
    group->m_gateway = std::move(gateway);
    group->m_shownUnit = Utf8(unit->GetStringSelection());
    group->Bind();
    return group;
}
void MeasurementQuantityGroup::Bind()
{
    const std::weak_ptr<MeasurementQuantityGroup> weak = shared_from_this();
    for (std::size_t index = 0; index < m_items.size(); ++index)
    {
        m_items[index].text->Bind(wxEVT_TEXT,
                                  [weak, index](wxCommandEvent&)
                                  {
                                      if (auto self = weak.lock())
                                      {
                                          if (!self->m_pending)
                                          {
                                              auto& item = self->m_items.at(index);
                                              item.input = {{"text", Utf8(item.text->GetValue())},
                                                            {"unit", self->m_shownUnit}};
                                              self->m_edited = true;
                                              if (self->onEdited)
                                              {
                                                  self->onEdited();
                                              }
                                          }
                                      }
                                  });
    }
    m_unit->Bind(wxEVT_CHOICE,
                 [weak](wxCommandEvent&)
                 {
                     if (auto self = weak.lock())
                     {
                         self->Convert();
                     }
                 });
}
Json MeasurementQuantityGroup::Input(std::size_t index) const
{
    const auto& item = m_items.at(index);
    if (item.input.is_object())
    {
        return item.input;
    }
    std::ostringstream text;
    if (item.value.is_number())
    {
        text << std::setprecision(17) << item.value.get<double>();
    }
    return {{"text", text.str()}, {"unit", "Hz"}};
}
bool MeasurementQuantityGroup::Edited() const
{
    return m_edited;
}
bool MeasurementQuantityGroup::Pending() const
{
    return m_pending;
}
void MeasurementQuantityGroup::Convert()
{
    if (!m_owner || m_pending)
    {
        return;
    }
    m_requestedUnit = Utf8(m_unit->GetStringSelection());
    if (m_requestedUnit == m_shownUnit)
    {
        return;
    }
    m_pending = true;
    m_display.clear();
    m_unit->Enable(false);
    for (auto& item : m_items)
    {
        item.text->Enable(false);
    }
    if (auto* okay = m_owner->FindWindow(wxID_OK))
    {
        okay->Enable(false);
    }
    if (onState)
    {
        onState();
    }
    ConvertNext(0);
}
void MeasurementQuantityGroup::ConvertNext(std::size_t index)
{
    if (!m_owner)
    {
        return;
    }
    if (index == m_items.size())
    {
        Finish("");
        return;
    }
    const auto& item = m_items.at(index);
    if ((!item.input.is_object() && item.value.is_null()) ||
        (item.input.is_object() && item.input.value("text", "").empty()))
    {
        m_display.push_back("");
        ConvertNext(index + 1);
        return;
    }
    const std::weak_ptr<MeasurementQuantityGroup> weak = shared_from_this();
    m_gateway(
        "measurement.quantity",
        {{"path", item.path}, {"value", item.value}, {"input", item.input}, {"display_unit", m_requestedUnit}}, false,
        [weak, index](const Json& response)
        {
            if (auto self = weak.lock())
            {
                if (!self->m_owner)
                {
                    return;
                }
                if (!response.value("text", Json(nullptr)).is_string())
                {
                    self->Finish("단위 환산 응답의 표시값이 없습니다.");
                    return;
                }
                self->m_display.push_back(response.at("text").get<std::string>());
                self->ConvertNext(index + 1);
            }
        },
        [weak](const Json& error)
        {
            if (auto self = weak.lock())
            {
                self->Finish(DiagnosticMessage(error));
            }
        });
}
void MeasurementQuantityGroup::Finish(const std::string& error)
{
    if (!m_owner)
    {
        return;
    }
    if (error.empty())
    {
        for (std::size_t index = 0; index < m_items.size(); ++index)
        {
            m_items[index].text->ChangeValue(Display(m_display.at(index)));
        }
        m_shownUnit = m_requestedUnit;
    }
    else
    {
        m_unit->SetStringSelection(Display(m_shownUnit));
    }
    m_pending = false;
    m_unit->Enable();
    for (auto& item : m_items)
    {
        item.text->Enable();
    }
    if (auto* okay = m_owner->FindWindow(wxID_OK))
    {
        okay->Enable();
    }
    if (!error.empty() && onStatus)
    {
        onStatus(error);
    }
    if (onState)
    {
        onState();
    }
}
