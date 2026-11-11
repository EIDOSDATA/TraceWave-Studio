/** @file @brief PCB 카탈로그 선택과 명시적 사용자 입력을 연결하는 대화상자이다. */
#pragma once

#include "pcb_selection_model.h"
#include "studio_types.h"
#include <wx/dialog.h>
#include <functional>
#include <array>
#include <string>
#include <vector>

class StudioSmokeDriver;
class wxButton;
class wxCheckBox;
class wxChoice;
class wxComboBox;
class wxGrid;
class wxListBox;
class wxListCtrl;
class wxNotebook;
class wxPanel;
class wxStaticText;
class wxTextCtrl;

/** @brief 공개 서비스 요청만 전달하며 프로젝트와 카탈로그 경로를 직접 열지 않는다. */
using DialogGateway = std::function<void(const std::string&, const Json&, bool, std::function<void(const Json&)>,
                                         std::function<void(const Json&)>)>;

/** @brief 입력 폼은 초안을 소유하고 확정 값과 물리 검증은 서비스에 위임한다. */
class PcbSelectionDialog final : public wxDialog
{
public:
    PcbSelectionDialog(wxWindow* parent, const Json& context, DialogGateway gateway);
    /** @brief 실제 적용 응답만 주 창에 전달한다. 취소 상태는 null이다. */
    const Json& GetAppliedResult() const;
    /** @brief 전송 단절을 읽기 실패와 미확정 적용으로 구분하고 재전송을 막는다. */
    void ServiceDisconnected(const std::string& message);

private:
    friend class StudioSmokeDriver;

    /** @brief 물성 하나의 독립된 값, 이유와 관측 연결을 표시한다. */
    struct PropertyControls
    {
        wxChoice* mode = nullptr;
        wxTextCtrl* value = nullptr;
        wxTextCtrl* reason = nullptr;
        wxStaticText* source = nullptr;
        std::string recordId;
        std::string catalogId;
    };

    void BuildInterface();
    wxPanel* BuildCatalogPage();
    wxPanel* BuildLayersPage();
    wxPanel* BuildMaterialsPage();
    wxPanel* BuildPortsPage();
    wxPanel* BuildReviewPage();
    void Search(int offset = 0);
    void SelectResult(long row);
    void UseSource();
    void UseManual();
    void PopulateLayers(const Json& rows, bool preserveExisting);
    void RefreshMaterialChoices();
    Json CollectSpecification();
    Json CollectPorts() const;
    Json ReadLayerRows() const;
    void Preview();
    void Apply();
    void Changed();
    void UpdateControls();
    void RenderPreview(const Json& result);
    void ShowFailure(const Json& error);
    void SetStatus(const std::string& message);
    void CloseDialog();
    void PaintSection(wxPaintEvent& event);
    void NewMaterial(bool discard = false);
    void LoadMaterial(int index);
    bool SaveMaterial();
    void RemoveMaterial();
    void AttachObservation(std::size_t property);
    void ClearObservation(std::size_t property);
    void MaterialChanged();

    Studio::PcbSelectionModel m_model;
    DialogGateway m_gateway;
    Json m_context;
    Json m_applied = nullptr;
    Json m_source = nullptr;
    Json m_rows = Json::array();
    Json m_materialSpecs = Json::array();
    Json m_materialIds = Json::object();
    Json m_selected = nullptr;
    Json m_sectionLayers = Json::array();
    Json m_searchResult = Json::object();
    std::string m_catalogId;
    std::string m_selectedCatalog;
    std::string m_selectedEntity;
    std::vector<int> m_pageOffsets{0};
    std::vector<std::string> m_layerIds;
    std::vector<std::string> m_layerLabels;
    std::vector<std::string> m_materialValues;
    std::vector<std::string> m_materialLabels;
    std::vector<std::string> m_materialReplaceIds;
    std::uint64_t m_filterRevision = 0;
    std::uint64_t m_detailRevision = 0;
    unsigned int m_materialCounter = 0;
    bool m_loading = false;
    bool m_manual = false;
    bool m_closed = false;
    bool m_applying = false;
    bool m_disconnected = false;
    bool m_materialDirty = false;
    int m_materialIndex = -1;

    wxNotebook* m_notebook = nullptr;
    wxChoice* m_entity = nullptr;
    wxComboBox* m_publisher = nullptr;
    wxTextCtrl* m_query = nullptr;
    wxListCtrl* m_results = nullptr;
    wxTextCtrl* m_detail = nullptr;
    wxButton* m_search = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_useSource = nullptr;
    wxButton* m_manualButton = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxGrid* m_layers = nullptr;
    wxTextCtrl* m_layoutReason = nullptr;
    wxTextCtrl* m_zOrigin = nullptr;
    wxButton* m_addLayer = nullptr;
    wxButton* m_removeLayer = nullptr;
    wxListBox* m_materials = nullptr;
    wxTextCtrl* m_materialName = nullptr;
    wxChoice* m_replaceMaterial = nullptr;
    std::array<PropertyControls, 3> m_properties;
    wxTextCtrl* m_bandMin = nullptr;
    wxTextCtrl* m_bandMax = nullptr;
    wxTextCtrl* m_bandReason = nullptr;
    wxGrid* m_ports = nullptr;
    wxTextCtrl* m_review = nullptr;
    wxPanel* m_section = nullptr;
    wxStaticText* m_status = nullptr;
    wxButton* m_previewButton = nullptr;
    wxButton* m_applyButton = nullptr;
    wxButton* m_cancelButton = nullptr;
};
