/** @file @brief 공개 결과 pin에 결합된 S11 표본을 화면에 전달한다. */
#pragma once

#include <nlohmann/json.hpp>

#include <optional>
#include <string>
#include <vector>

class PrototypeResult
{
public:
    struct Series
    {
        std::string label;
        std::string revision;
        nlohmann::json source;
        nlohmann::json pin;
        nlohmann::json references;
        std::size_t total = 0;
        std::vector<double> frequenciesGhz;
        std::vector<double> magnitudeDb;
    };

    struct SavedResult
    {
        std::string artifact;
        std::string label;
        std::string revision;
        bool available = false;
    };

    void requestHistory(int direction);
    nlohmann::json historyInput() const;
    void acceptHistory(const nlohmann::json& reply, const std::string& project);
    void setHistoryStatus(std::string status);
    bool canBrowseHistory(int direction) const;
    bool browseHistory(int direction);
    const SavedResult* historyChoice() const;
    const std::string& historyStatus() const { return historyStatus_; }

    bool acceptLatest(const nlohmann::json& reply);
    void selectArtifact(const std::string& artifact, const std::string& revision = {});
    void acceptDescription(const nlohmann::json& reply, const std::string& project, const std::string& revision);
    bool acceptPage(const nlohmann::json& reply);
    nlohmann::json descriptionInput() const;
    nlohmann::json pageInput() const;
    void setStatus(std::string status);

    const std::optional<Series>& series() const { return series_; }
    const std::string& status() const { return status_; }

private:
    static constexpr std::size_t pageLimit = 201;
    static constexpr std::size_t historyLimit = 16;
    std::vector<SavedResult> history_;
    std::string historyStatus_;
    std::string historyHash_;
    std::size_t historyOffset_ = 0;
    std::size_t historyTotal_ = 0;
    std::size_t historyIndex_ = 0;
    std::size_t requestedOffset_ = 0;
    int requestedDirection_ = 0;
    Series pending_;
    std::optional<Series> series_;
    std::string status_;
};
