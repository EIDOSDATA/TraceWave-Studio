/** @file @brief 전체 Studio에 도킹된 실제 3D 캔버스의 입력과 Windows 합성을 계측한다. */
#pragma once

#include "studio_types.h"
#include <memory>
#include <wx/timer.h>

class ModelView;

class StudioModelDisplayProbe final : private wxTimer
{
public:
    explicit StudioModelDisplayProbe(ModelView& model);
    ~StudioModelDisplayProbe() override;
    bool Complete() const;
    Json Finish();

private:
    struct State;
    std::unique_ptr<State> m_state;
    void Notify() override;
};
