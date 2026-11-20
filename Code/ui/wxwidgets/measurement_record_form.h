/** @file @brief 시료, 교정과 측정 조건의 원문과 수정 초안을 분리하는 native 폼이다. */
#pragma once
#include "dialog_gateway.h"
#include "measurement_recovery.h"
#include <wx/scrolwin.h>
#include <map>
#include <memory>

class wxTextCtrl;
class wxChoice;
class wxBoxSizer;
class wxListCtrl;
class wxButton;

/** @brief 미정값을 채우지 않고 변경한 필드만 서비스에 전달한다. */
class MeasurementRecordForm final : public wxScrolledWindow
{
public:
    MeasurementRecordForm(wxWindow* parent, DialogGateway gateway);
    void SetRecord(const Json& record, const Json& context);
    void SetDescriptor(const Json& descriptor);
    void SetRecovery(std::shared_ptr<MeasurementRecovery> recovery);
    void AddAttachment(const Json& attachment);
    Json Changes() const;
    std::string Name() const;
    std::string Reason() const;
    bool Dirty() const;
    bool Pending() const;
    std::function<void()> onChanged;
    std::function<void()> onStateChanged;
    std::function<void(const std::string&)> onStatus;

private:
    friend class StudioSmokeDriver;
    struct Field
    {
        std::string path, kind;
        Json original = nullptr, rawInput = nullptr;
        wxTextCtrl* text = nullptr;
        wxChoice* evidence = nullptr;
        wxChoice* unit = nullptr;
        wxTextCtrl* sources = nullptr;
        std::string shownUnit;
        bool changed = false, loading = false;
        std::uint64_t generation = 0;
    };
    void BuildSection(wxWindow* parent, wxBoxSizer* layout, const std::string& section, const std::string& title);
    void BuildCollections(wxBoxSizer* layout);
    void ChangeField(const std::shared_ptr<Field>& field);
    void ChangeUnit(const std::shared_ptr<Field>& field);
    void Changed();
    void EditCollection(const std::string& key);
    void RefreshCollections();
    void UploadAttachment();
    Json m_record = Json::object(), m_context = Json::object();
    Json m_collections = Json::object();
    Json m_collectionInputs = Json::object();
    std::map<std::string, bool> m_collectionChanged;
    std::vector<std::shared_ptr<Field>> m_fields;
    DialogGateway m_gateway;
    std::shared_ptr<MeasurementRecovery> m_recovery;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_author = nullptr;
    wxTextCtrl* m_sources = nullptr;
    wxChoice* m_class = nullptr;
    wxListCtrl* m_collectionList = nullptr;
    std::string m_originalName, m_originalReason, m_originalAuthor, m_originalSources;
    int m_originalClass = 0;
    bool m_loading = false;
    int m_pending = 0;
    std::uint64_t m_generation = 0;
};
