/** @file @brief 프로젝트가 소유한 대용량 필드·복소 곡선의 등록 및 조회 창이다. */
#pragma once

#include "dialog_gateway.h"
#include <filesystem>
#include <future>
#include <wx/dialog.h>
#include <wx/timer.h>

class FieldResultView;
class NetworkChart;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxSimplebook;
class wxSpinCtrl;
class wxStaticText;
class wxTextCtrl;

class LargeResultDialog final : public wxDialog
{
public:
    LargeResultDialog(wxWindow* parent, std::filesystem::path project, std::string revision, DialogGateway gateway);
    void StartSmoke(Json fixture);

private:
    void Reload();
    void Select(int index);
    void ChooseFile(const std::string& kind);
    void StartImport(const std::filesystem::path& file, const std::string& kind);
    void ChooseTransferDestination();
    void StartTransfer(const std::filesystem::path& file);
    void SaveTransfer(const Json& artifact);
    void Poll(wxTimerEvent&);
    void ReadField(const Json& selection);
    void ReadCurves();
    void Status(const std::string& message, bool pending = false);
    void SmokeTick();
    void SmokeFinish(const std::string& error = {});
    void Error(const Json& error);
    bool SameRecord(const Json& value) const;
    std::filesystem::path m_project;
    std::string m_revision;
    DialogGateway m_gateway;
    wxTimer m_timer;
    wxListCtrl* m_records = nullptr;
    wxListCtrl* m_sources = nullptr;
    wxSimplebook* m_pages = nullptr;
    FieldResultView* m_field = nullptr;
    NetworkChart* m_chart = nullptr;
    wxStaticText* m_status = nullptr;
    wxTextCtrl* m_details = nullptr;
    wxTextCtrl* m_sourceDetail = nullptr;
    wxChoice* m_mode = nullptr;
    wxChoice* m_metric = nullptr;
    wxSpinCtrl* m_offset = nullptr;
    wxButton* m_importField = nullptr;
    wxButton* m_importTraces = nullptr;
    wxButton* m_importPackage = nullptr;
    wxButton* m_exportPackage = nullptr;
    wxButton* m_readCurves = nullptr;
    Json m_catalog = Json::array(), m_record, m_curvePage, m_import;
    std::future<std::string> m_copy;
    std::filesystem::path m_transferDestination;
    std::string m_job;
    bool m_busy = false;
    bool m_poll = false;
    Json m_fixture, m_evidence;
    unsigned m_smokeStep = 0;
    unsigned m_smokeSlices = 0;
    Clock::time_point m_baselineUntil{};
};
