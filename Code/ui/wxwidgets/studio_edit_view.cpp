/** @file @brief 개정에 결합된 편집 페이지를 모두 받은 뒤 화면에 반영한다. */
#include "studio_internal.h"
#include "editor_sync.h"

namespace
{
/** @brief 신뢰 경계의 화면 전체 행 수와 단일 페이지 행 수를 제한한다. */
constexpr std::size_t MaximumEditRows = 64000;
constexpr std::size_t MaximumPageRows = 512;

/** @brief 행을 전송하기 위해 분리한 선택지를 원래 속성 위치로 되돌린다. */
void JoinChoices(Json& editor)
{
    auto& fields = editor.at("selection").at("fields");
    for (auto& choice : editor.at("view_choices"))
    {
        const int index = choice.at(0).get<int>();
        auto& list = index == -1 ? editor.at("coordinate_choices") : fields.at(index).at("choices");
        list.push_back(std::move(choice.at(1)));
    }
    editor.erase("view_choices");
}
}

/** @brief 다른 개정, 중복 순서, 비정상 크기를 차단하고 기존 DTO의 배열만 연결한다. */
void StudioFrame::ReadEditPages(bool canvas, Json input, std::shared_ptr<Json> assembled,
                                std::function<void(Json)> completed)
{
    const auto project = m_project;
    const auto revision = m_revision;
    const std::size_t offset = input.at("offset").get<std::size_t>();
    Send(canvas ? "canvas.page" : "editor.page", input, false, Context(),
         [this, project, revision, offset, canvas, input, assembled, completed](const Json& result) mutable
         {
             if (m_closing || project != m_project || revision != m_revision)
             {
                 return;
             }
             const bool matches = canvas ? Studio::MatchesCanvas(result, project, revision)
                                         : Studio::MatchesEditor(result, project, revision);
             const auto& page = result.at("page");
             const auto total = page.at("total").get<std::size_t>();
             if (!matches || page.value("profile", "") != Studio::EditViewPagesProfile ||
                 page.at("offset") != offset || offset > total || total > MaximumEditRows ||
                 (offset != 0 && assembled->at("page").at("total") != total))
             {
                 throw std::runtime_error("편집 표시 페이지가 현재 개정 또는 전송 범위와 다릅니다.");
             }
             const std::array<const char*, 3> names = canvas
                 ? std::array<const char*, 3>{"shapes", "omissions", "pcb_features"}
                 : std::array<const char*, 3>{"items", "view_choices", nullptr};
             std::size_t count = 0;
             if (offset == 0)
             {
                 *assembled = result;
             }
             for (const auto* name : names)
             {
                 if (name == nullptr)
                 {
                     continue;
                 }
                 const auto rows = result.find(name);
                 if (rows == result.end() && canvas && std::string_view(name) == "pcb_features" &&
                     !assembled->contains(name))
                 {
                     continue;
                 }
                 if (rows == result.end() || !rows->is_array())
                 {
                     throw std::runtime_error("편집 표시 행 목록이 올바르지 않습니다.");
                 }
                 count += rows->size();
                 if (offset != 0)
                 {
                     auto& destination = assembled->at(name);
                     destination.insert(destination.end(), rows->begin(), rows->end());
                 }
             }
             const auto& next = page.at("next");
             if (count > MaximumPageRows || count > total - offset ||
                 (next.is_null() ? offset + count != total
                                 : count == 0 || next != offset + count || offset + count >= total))
             {
                 throw std::runtime_error("편집 표시 페이지의 행 수나 다음 위치가 올바르지 않습니다.");
             }
             if (!next.is_null())
             {
                 input["offset"] = next;
                 ReadEditPages(canvas, std::move(input), assembled, completed);
                 return;
             }
             assembled->erase("page");
             if (!canvas)
             {
                 JoinChoices(*assembled);
             }
             completed(std::move(*assembled));
         });
}
