/** @file @brief 기술 도면의 입력과 실제 종이 미리보기를 구성하는 native View이다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
#include <vector>
class DrawingSheetCanvas;
class wxChoice;
class wxCheckBox;
class wxCheckListBox;
class wxSpinCtrlDouble;
class wxButton;
class wxStaticText;

class DrawingOutputView final : public wxScrolledWindow
{
public:
    explicit DrawingOutputView(wxWindow* parent);
    void SetContext(const Json& context);
    void SetStoredAnnotation(const Json& settings);
    Json Options() const;
    std::string Format() const;
    void SetPreview(const Json& review);
    void ClearPreview(const std::string& message);
    void SetAvailable(bool available, bool busy, bool reviewed, bool hasSnapshot = true);
    std::function<void()> onChanged;
    std::function<void()> onPreview;
    std::function<void()> onBuild;
    std::function<void(const Json&)> onSaveAnnotations;

private:
    /** @brief 사용자가 명시한 mm 영역만 상세 뷰로 추가한다. */
    void AddDetail();
    friend class StudioSmokeDriver;
    void Changed();
    void UpdateMode();
    void EditAnnotations();
    void InspectAnnotations();
    void EditPlacement();
    void MoveDimension(const Json& item, const Json& point);
    Json CurrentAnnotation() const;
    void KeepAnnotationView();
    void UpdateAnnotationActions();
    DrawingSheetCanvas* m_canvas = nullptr;
    wxChoice* m_format = nullptr;
    wxChoice* m_mode = nullptr;
    wxChoice* m_sheet = nullptr;
    wxChoice* m_orientation = nullptr;
    wxChoice* m_page = nullptr;
    wxSpinCtrlDouble* m_scale = nullptr;
    wxCheckListBox* m_views = nullptr;
    wxCheckBox* m_dimensions = nullptr;
    wxCheckBox* m_notes = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_detailAdd = nullptr;
    wxButton* m_detailRemove = nullptr;
    wxButton* m_build = nullptr;
    wxButton* m_annotationEdit = nullptr;
    wxButton* m_annotationSave = nullptr;
    wxButton* m_annotationInspect = nullptr;
    wxButton* m_placementEdit = nullptr;
    wxStaticText* m_summary = nullptr;
    std::vector<Json> m_viewValues;
    bool m_refreshing = false;
    Json m_annotationCatalog = Json::object();
    Json m_annotation = nullptr;
    Json m_storedAnnotation = nullptr;
    Json m_annotationReview = nullptr;
    Json m_placements = nullptr;
    bool m_available = false;
    bool m_hasSnapshot = false;
};
