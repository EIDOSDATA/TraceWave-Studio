#pragma once

#include "accessibility.h"

class PrototypeProject;

/** @brief 문헌 카드의 입력과 적용 전 검토 탭을 표시한다. */
class PrototypeTemplatePanel
{
public:
    bool draw(PrototypeProject& project, accessibility::Bridge& access, accessibility::Control& focus);
    void action(PrototypeProject& project, accessibility::Control control);

private:
    bool review_ = false;
    int fieldGeneration_ = 0;
};
