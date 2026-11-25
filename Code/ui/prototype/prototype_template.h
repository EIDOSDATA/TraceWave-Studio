#pragma once

#include "../wxwidgets/canvas_scene.h"

#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

/** @brief 문헌 후보의 입력 사본과 개정에 봉인된 미리보기를 따로 보관한다. */
class PrototypeTemplate
{
public:
    struct Field
    {
        std::string key;
        std::string label;
        std::string unit;
        std::string original;
        std::string value;
        bool fromCard = false;
    };

    struct Draft
    {
        std::vector<Field> fields;
        std::size_t recipe = 0;
        std::string frequency;
        std::string frequencyUnit = "GHz";
        std::string assumption;
        bool goalDimension = false;

        bool dirty() const;
    };

    struct Review
    {
        std::string hash;
        std::string notes;
        std::optional<CanvasScene::Model> scene;
        std::vector<std::string> generated;
    };

    void acceptContext(const nlohmann::json& reply, const std::string& project, const std::string& revision);
    void acceptPreview(const nlohmann::json& reply, const std::string& project, const nlohmann::json& specification);
    void acceptApply(const nlohmann::json& reply, const std::string& project, const nlohmann::json& specification);
    void selectCard(std::size_t index);
    void selectMode(std::size_t index);
    void selectLayer(std::size_t index);
    void selectTarget(std::size_t index);
    void discard();
    void invalidate(const std::string& revision);
    void clearReview();

    bool dirty() const;
    bool ready() const;
    bool canApply() const;
    bool hasContext() const { return context_.is_object(); }
    const nlohmann::json& context() const { return context_; }
    const nlohmann::json& card() const;
    const nlohmann::json& modes() const;
    const std::optional<Review>& review() const { return review_; }
    Draft& draft();
    nlohmann::json specification() const;
    nlohmann::json application(const std::string& command) const;
    std::size_t cardIndex() const { return card_; }
    std::size_t layerIndex() const { return layer_; }
    std::size_t targetIndex() const { return target_; }
    std::size_t modeIndex() const { return mode_; }
    std::string status;

private:
    using Key = std::tuple<std::string, std::string, std::size_t>;
    Key draftKey() const;
    nlohmann::json context_;
    nlohmann::json reviewed_;
    std::optional<Review> review_;
    std::map<Key, Draft> drafts_;
    std::size_t card_ = 0;
    std::size_t layer_ = 0;
    std::size_t target_ = 0;
    std::size_t mode_ = 0;
};
