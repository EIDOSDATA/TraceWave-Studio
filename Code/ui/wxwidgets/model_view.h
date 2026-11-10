#pragma once

#include <wx/wx.h>
#include <nlohmann/json.hpp>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

/** @brief 게시된 표시용 삼각형만 비동기로 읽는 지연 생성 3D 화면이다. */
class ModelView final : public wxPanel
{
public:
    using Json = nlohmann::json;

    explicit ModelView(wxWindow* parent);
    ~ModelView() override;
    /** @brief 파일 참조와 같은 바이트의 SHA256을 background에서 확인한다. */
    bool LoadArtifact(const wxString& workspace, const Json& artifact, const Json& snapshot, const std::string& runId);
    void Clear();
    void SetSelection(const std::string& identity);
    void SetLayerVisible(const std::string& identity, bool visible);
    void FitView();
    void SetView(const std::string& view);
    bool HasMesh() const;
    bool IsLoading() const;
    std::string Error() const;
    std::string LoadedSnapshotId() const;
    std::string Selection() const;
    std::string RendererDescription() const;
    std::size_t TriangleCount() const;
    std::size_t BodyCount() const;
    std::uint64_t RenderedFrameCount() const;

    std::function<void(const std::string&)> onStatus;
    std::function<void(const std::string&)> onSelection;

private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
