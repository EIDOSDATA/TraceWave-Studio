#pragma once

#include "accessibility.h"
#include "prototype_setup.h"

class PrototypeProject;

/** @brief 설정 폼과 검토 결과의 Windows 작업 영역을 표시한다. */
class PrototypeSetupPanel
{
public:
    bool draw(PrototypeProject& project, accessibility::Bridge& access, accessibility::Control& focus);
    bool action(PrototypeProject& project, accessibility::Control control);
    bool takeJump();

private:
    void select(PrototypeProject& project, PrototypeSetup::Page page, std::string section,
        std::string record = {}, std::string target = {}, std::string parameter = {});
    bool drawContext(PrototypeProject& project, accessibility::Bridge& access, accessibility::Control& focus);
    bool drawCatalog(PrototypeProject& project, accessibility::Bridge& access, accessibility::Control& focus);
    const nlohmann::json* finding(const PrototypeSetup& model) const;

    bool remove_ = false;
    std::size_t issue_ = 0;
    int scope_ = 0;
    int fieldGeneration_ = 0;
    bool showAll_ = false;
    bool jump_ = false;
};
