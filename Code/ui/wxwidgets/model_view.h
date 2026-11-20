#pragma once

#include <wx/wx.h>
#include <nlohmann/json.hpp>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

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
    /** @brief 드래그와 같은 카메라 회전/이동을 픽셀 변화량으로 적용한다. */
    void RotateView(double dx, double dy);
    void PanView(double dx, double dy);
    bool HasMesh() const;
    bool IsLoading() const;
    std::string Error() const;
    std::string LoadedSnapshotId() const;
    std::string Selection() const;
    /** @brief 선택 원본 ID에 연결된 3D 바디 역할을 조회한다. */
    std::string SourceRole(const std::string& id) const;
    std::string RendererDescription() const;
    /** @brief 실제 상태와 전송 횟수를 시험 기록에 제공한다. */
    Json VertexBufferDiagnostics() const;
    std::size_t TriangleCount() const;
    std::size_t BodyCount() const;
    std::uint64_t RenderedFrameCount() const;

    std::function<void(const std::string&)> onStatus;
    /** @brief 전용 계측 창에서 첫 파일을 열기 전에 지정하는 OpenGL 버퍼 표식이다. */
    std::function<void(wxWindow&)> onDrawDisplayMarker;
    std::function<void(const std::string&)> onSelection;
    /** @brief 병합 바디의 원본을 사용자에게 고르게 하며 첫 원본을 자동 채택하지 않는다. */
    std::function<void(const std::vector<std::string>&)> onSelectionCandidates;

private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
