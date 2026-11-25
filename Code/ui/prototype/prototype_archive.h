/** @file @brief 봉인 ZIP의 검토와 승인 복원을 기존 서비스 호출로 제공한다. */
#pragma once

#include <filesystem>
#include <future>
#include <string>
#include <nlohmann/json.hpp>

struct SDL_Window;
class PrototypeService;

class PrototypeArchive
{
public:
    bool busy() const;
    bool canChoose() const;
    bool canApprove() const;
    bool canCancel() const;
    void choose();
    void approve();
    void cancel();
    void update(SDL_Window* window, PrototypeService& service);

    const std::string& status() const { return status_; }
    const nlohmann::json& review() const { return review_; }
    const std::string& restoredPath() const { return restored_; }

private:
    enum class Phase { idle, choose, read, begin, chunk, review, approval, reserve, apply, drop };
    struct File
    {
        std::string bytes;
        std::string sha;
    };
    static File readFile(const std::filesystem::path& path);
    void accept(const nlohmann::json& result);
    void complete(const nlohmann::json& result);
    nlohmann::json approval() const;
    void clear();

    Phase phase_ = Phase::idle;
    File file_;
    std::future<File> read_;
    std::string upload_;
    std::string restored_;
    std::string status_;
    nlohmann::json review_;
    std::size_t position_ = 0;
    std::size_t sent_ = 0;
    bool waiting_ = false;
    bool cancelling_ = false;
};
