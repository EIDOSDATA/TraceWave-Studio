/** @file @brief 측정 목록 입력을 원시 JSON 없이 기능별 native 편집기로 제공한다. */
#pragma once
#include "dialog_gateway.h"
class wxWindow;

struct MeasurementCollectionEdit
{
    bool accepted = false;
    bool quantity = false;
    Json value = nullptr;
};

MeasurementCollectionEdit EditMeasurementCollection(wxWindow* parent, const std::string& key, const Json& current,
                                                    const Json& context, DialogGateway gateway);
MeasurementCollectionEdit EditMeasurementUncertainty(wxWindow* parent, const Json& current, const Json& context,
                                                     DialogGateway gateway);
MeasurementCollectionEdit EditMeasurementProcessing(wxWindow* parent, const Json& current, const Json& context);
