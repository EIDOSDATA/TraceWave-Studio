/** @file @brief 게시된 KiCad 보드에서 제조 교환 후보 파일을 생성한다. */
#pragma once

#include "prototype_exchange.h"

#include <future>
#include <string>

struct SDL_Window;
struct PrototypeServiceOptions;

class PrototypeManufacturing
{
public:
    bool active() const { return result_.valid(); }
    void chooseFormat();
    const char* format() const;
    const std::string& status() const { return status_; }
    void select(const PrototypeExchange::Published& board);
    void update(SDL_Window* window, const PrototypeServiceOptions& options);

private:
    std::optional<PrototypeExchange::Published> selected_;
    std::size_t format_ = 0;
    std::string status_;
    std::future<std::string> result_;
};
