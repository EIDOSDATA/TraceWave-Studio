#pragma once

#include "prototype_project.h"

#include <imgui.h>

/** @brief 끝점 위치 입력과 현재의 미적용 미리보기를 화면에 전달한다. */
struct PrototypeEndpoint
{
    std::string id;
    std::string revision;
    CanvasPrecision::Endpoint side = CanvasPrecision::Endpoint::End;
    CanvasScene::Point point{};
    bool picking = false;
    bool snap = true;
    std::string snapLabel;
};

/** @brief 같은 개정의 실제 2D 장면을 그리고 화면 선택을 서비스 객체 식별자로 보존한다. */
bool drawProjectCanvas(PrototypeProject::View& view, float& zoom, ImVec2& pan, PrototypeEndpoint* endpoint = nullptr);
