/** @file @brief 프로젝트에 게시된 3D 표시 자료를 작업 스레드에서 검증한다. */
#pragma once

#include "../wxwidgets/display_mesh.h"

#include <future>

class PrototypeCad
{
public:
    using Scene = std::shared_ptr<const DisplayMesh::Scene>;

    explicit PrototypeCad(const char* workspace);
    ~PrototypeCad();

    void accept(const nlohmann::json& reply, const std::string& project);
    bool load(const nlohmann::json& result, const std::string& project);
    void poll();
    void setStatus(std::string status);

    bool loading() const { return pending_.valid(); }
    const Scene& scene() const { return scene_; }
    const std::string& status() const { return status_; }

private:
    std::filesystem::path workspace_;
    std::atomic<bool> cancelled_{false};
    std::future<Scene> pending_;
    Scene scene_;
    std::string status_;
};
