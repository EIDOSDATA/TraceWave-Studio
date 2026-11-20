/** @file @brief 실제 Windows 카탈로그 표의 연속 스크롤 합성을 관찰한다. */
#pragma once

#include "studio_types.h"
#include <memory>
#include <wx/timer.h>

class PcbCatalogTable;

/** @brief 명시적으로 활성화한 실제 표의 시험에서만 Win32 스크롤과 합성 시각을 대응한다. */
class StudioCatalogDisplayProbe final : private wxTimer
{
public:
    explicit StudioCatalogDisplayProbe(PcbCatalogTable& table);
    ~StudioCatalogDisplayProbe() override;
    bool Complete() const;
    Json Finish();

private:
    struct State;
    std::unique_ptr<State> m_state;
    void Notify() override;
};
