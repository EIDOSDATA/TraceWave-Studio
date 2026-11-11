/** @file @brief 위젯과 서비스 전송에서 분리한 PCB 선택의 입력 및 비동기 검토 상태이다. */
#pragma once

#include <nlohmann/json.hpp>
#include <cstdint>
#include <string>

namespace Studio
{
using Json = nlohmann::json;

/** @brief 서비스가 검토한 동일 개정/입력만 적용하도록 보장하는 presentation model이다. */
class PcbSelectionModel final
{
public:
    using Token = std::uint64_t;
    enum class Stage
    {
        Editing,
        Searching,
        LoadingDraft,
        Previewing,
        Reviewed,
        Applying,
        Applied,
        Stale
    };

    /** @brief 서버 context와 새 선택 UUID를 고정하고 기존 적층 유지 입력으로 시작한다. */
    PcbSelectionModel(const Json& context, const std::string& selectionId);
    void Reset(const Json& context, const std::string& selectionId);

    /** @brief search/draft/preview/apply 요청을 시작하고 이전 비동기 응답을 무효화한다. */
    Token BeginRequest(const std::string& channel);
    /** @brief 현재 검색 응답만 표시하며 개체 ID를 숫자로 변환하지 않는다. */
    bool AcceptSearch(Token token, const Json& result);
    /** @brief 동일 카탈로그/개체 초안만 채택하고 이전 층 대응과 두께 수정을 비운다. */
    bool SelectSource(Token token, const Json& source, const Json& draft);
    /** @brief 폼이 명시한 specification을 복사하고 이전 preview 승인을 제거한다. */
    void SetSpecification(const Json& specification);
    /** @brief 현재 revision과 고정 선택 ID를 포함한 읽기 전용 검토 입력이다. */
    Json PreviewInput() const;
    /** @brief 요청 당시 개정과 선택 ID가 일치하는 권위 응답만 적용 자격을 갖는다. */
    bool AcceptPreview(Token token, const Json& result);
    /** @brief 권위 preview가 허용한 해시와 동일 입력만 변경 명령으로 반환한다. */
    Json ApplyInput(const std::string& commandId) const;
    /** @brief 성공 응답을 확인하고 이 대화 상자의 추가 변경을 막는다. */
    bool AcceptApply(Token token, const Json& result);
    /** @brief 현재 요청의 실패만 표시하고 적용 실패의 preview를 다시 승인하지 않는다. */
    bool Fail(Token token, const Json& error);
    /** @brief 검색 조건 또는 아직 파싱하지 못한 폼 변경도 기존 적용 승인을 제거한다. */
    void Invalidate();
    /** @brief 프로젝트가 외부에서 변경되면 새 context로 재시작하기 전 적용을 막는다. */
    void MarkStale();

    const Json& Context() const;
    const Json& Specification() const;
    const Json& SearchResult() const;
    const Json& Draft() const;
    const Json& Preview() const;
    const Json& AppliedResult() const;
    const Json& Error() const;
    bool IsCurrent(Token token) const;
    const std::string& SelectionId() const;
    const std::string& Revision() const;
    Stage CurrentStage() const;
    std::string StageName() const;
    bool Dirty() const;
    bool CanApply() const;

    /** @brief 기존/원문/수동 층을 mm 단위 그대로 표시하며 미정과 0을 구분한다.
     * @return key/name/role/thickness_mm/z_min_mm/existing_layer_id/material_id/
     * parameter_bound/status/reason/overridden/source_thickness_mm 필드를 가진 목록이다.
     */
    Json LayerRows() const;
    /** @brief 서버 preview.candidate_layers만 단면에 사용하며 SI 변환이나 누적 계산을 하지 않는다. */
    Json CandidateLayers() const;

private:
    void RequireEditable() const;
    void ClearReview();
    bool Matches(Token token, const std::string& channel) const;

    Json m_context;
    Json m_specification;
    Json m_search = Json::object();
    Json m_draft = nullptr;
    Json m_preview = nullptr;
    Json m_error = nullptr;
    Json m_reviewedInput = nullptr;
    Json m_appliedResult = nullptr;
    std::string m_selectionId;
    std::string m_revision;
    std::string m_channel;
    Token m_sequence = 0;
    Token m_activeToken = 0;
    Stage m_stage = Stage::Editing;
    bool m_dirty = false;
};
}
