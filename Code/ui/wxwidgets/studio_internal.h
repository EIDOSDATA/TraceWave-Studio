/** @file @brief 화면 구현에서만 사용하는 위젯과 명령 식별자다. */
#pragma once
#include <wx/wx.h>
#include <wx/cmdline.h>
#include <wx/splitter.h>
#include <wx/treectrl.h>
#include <wx/filename.h>
#include <wx/accel.h>
#include <wx/aui/aui.h>
#include <wx/listctrl.h>
#include <wx/listbox.h>
#include <wx/checklst.h>
#include <wx/notebook.h>
#include <wx/spinctrl.h>
#include <nlohmann/json.hpp>
#include <objbase.h>

#include <chrono>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <utility>

#include "service_client.h"
#include "editor_panel.h"
#include "design_canvas.h"
#include "model_view.h"
#include "solver_chart.h"
#include "polygon_input.h"

#include "studio_frame.h"
#include "studio_support.h"
#include "studio_smoke.h"

enum
{
    IdCreate = wxID_HIGHEST + 1,
    IdOpen,
    IdSave,
    IdSnapshot,
    IdApply,
    IdNewParameter,
    IdUndo,
    IdRedo,
    IdRefresh,
    IdBoard,
    IdCircularBoard,
    IdNewMaterial,
    IdPcbSelection,
    IdNewNet,
    IdNewPort,
    IdRunSolver,
    IdCancelSolver,
    IdRadiation,
    IdProjectStudy,
    IdLayer,
    IdDielectric,
    IdExportStep,
    IdBuild3D,
    IdCancelCad,
    IdOutputFolder,
    IdFit3D,
    IdTop3D,
    IdIso3D,
    IdSelect,
    IdLine,
    IdArc,
    IdCoordinates,
    IdPolygon,
    IdCirclePad,
    IdRectanglePad,
    IdVia,
    IdFit,
    IdDeleteShape,
    IdValidate,
    IdResetLayout,
    IdTargets,
    IdTemplates,
    IdTimer,
    IdShutdown
};

/** @brief 트리 항목을 서비스가 사용하는 안정 객체 ID에 결합한다. */
class SelectionData final : public wxTreeItemData
{
public:
    explicit SelectionData(Json value) : selection(std::move(value)) {}
    Json selection;
};
