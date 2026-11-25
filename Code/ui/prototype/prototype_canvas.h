#pragma once

#include "prototype_project.h"

#include <imgui.h>

/** @brief 같은 개정의 실제 2D 장면을 그리고 화면 선택을 서비스 객체 식별자로 보존한다. */
bool drawProjectCanvas(PrototypeProject::View& view, float& zoom, ImVec2& pan);
