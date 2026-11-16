#pragma once

#include "canvas_scene.h"

/** @brief 장면 좌표와 픽셀 좌표의 변환 및 native 표시 범위를 한 곳에서 계산한다. */
struct CanvasViewport
{
    using Point = CanvasGeometry::Point;
    int width;
    int height;
    Point center;
    double pixelsPerMm;

    /** @brief 그리드와 스냅이 동일한 표시 눈금을 사용한다. */
    double GridStep() const;
    Point Project(Point point, Point offset = {0.0, 0.0}) const;
    Point Unproject(Point pixel) const;
    bool Renderable(const CanvasScene::Shape& shape, Point offset = {0.0, 0.0}) const;
};
