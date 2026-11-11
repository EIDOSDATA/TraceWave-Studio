/** @file @brief PCB 선택의 변경, 비동기 응답 및 권위 미리보기 승인 상태를 관리한다. */
#include "pcb_selection_model.h"
#include "pcb_selection_model_data.h"
#include <limits>

namespace Studio
{
using PcbSelectionData::Require;

PcbSelectionModel::PcbSelectionModel(const Json& context, const std::string& selectionId)
{
    Reset(context, selectionId);
}

void PcbSelectionModel::Reset(const Json& context, const std::string& selectionId)
{
    Require(m_stage != Stage::Applying, "적용 결과를 확인하기 전에 선택 문맥을 바꿀 수 없습니다.");
    ClearReview();
    m_stage = Stage::Stale;
    PcbSelectionData::Context(context);
    PcbSelectionData::Uuid(selectionId);
    m_context = context;
    m_selectionId = selectionId;
    m_revision = context.at("revision_id").get<std::string>();
    m_specification = Json{{"source", nullptr}, {"materials", Json::array()}};
    m_search = Json::object();
    m_draft = nullptr;
    m_appliedResult = nullptr;
    ClearReview();
    m_stage = Stage::Editing;
    m_dirty = false;
}

void PcbSelectionModel::RequireEditable() const
{
    Require(m_stage != Stage::Applying && m_stage != Stage::Applied && m_stage != Stage::Stale,
            "현재 선택은 입력을 바꿀 수 없습니다. 프로젝트 문맥을 다시 여십시오.");
}

void PcbSelectionModel::ClearReview()
{
    m_preview = nullptr;
    m_reviewedInput = nullptr;
    m_error = nullptr;
    m_activeToken = 0;
    m_channel.clear();
}

void PcbSelectionModel::Invalidate()
{
    RequireEditable();
    ClearReview();
    m_stage = Stage::Editing;
    m_dirty = true;
}

void PcbSelectionModel::MarkStale()
{
    ClearReview();
    m_stage = Stage::Stale;
}

PcbSelectionModel::Token PcbSelectionModel::BeginRequest(const std::string& channel)
{
    Require(channel == "search" || channel == "draft" || channel == "preview" || channel == "apply",
            "지원하지 않는 PCB 화면 요청입니다.");
    Require(m_sequence != std::numeric_limits<Token>::max(), "화면 요청 토큰을 더 발급할 수 없습니다.");
    if (channel == "apply")
    {
        Require(CanApply(), "현재 입력의 적용 가능한 미리보기가 필요합니다.");
        m_stage = Stage::Applying;
    }
    else
    {
        Invalidate();
        if (channel == "preview")
        {
            m_reviewedInput = PreviewInput();
            m_stage = Stage::Previewing;
        }
        else if (channel == "draft")
        {
            m_stage = Stage::LoadingDraft;
        }
        else
        {
            m_stage = Stage::Searching;
        }
    }
    m_channel = channel;
    m_activeToken = ++m_sequence;
    return m_activeToken;
}

bool PcbSelectionModel::IsCurrent(Token token) const
{
    return token != 0 && token == m_activeToken;
}

bool PcbSelectionModel::Matches(Token token, const std::string& channel) const
{
    return IsCurrent(token) && m_channel == channel;
}

bool PcbSelectionModel::AcceptSearch(Token token, const Json& result)
{
    if (!Matches(token, "search"))
    {
        return false;
    }
    PcbSelectionData::Bounded(result);
    Require(result.is_object() && result.contains("items") && result.at("items").is_array(),
            "카탈로그 검색 응답이 올바르지 않습니다.");
    m_search = result;
    m_activeToken = 0;
    m_stage = Stage::Editing;
    return true;
}

bool PcbSelectionModel::SelectSource(Token token, const Json& source, const Json& draft)
{
    if (!Matches(token, "draft"))
    {
        return false;
    }
    PcbSelectionData::Source(source);
    Require(!source.is_null(), "원문 초안 선택에 출처가 필요합니다.");
    PcbSelectionData::Draft(source, draft);
    Json next = m_specification;
    const auto previousCatalog = next.value("catalog_id", Json(nullptr));
    const auto previousSource = next.at("source");
    const auto catalog = source.at("catalog_id");
    if ((!previousSource.is_null() && previousSource.at("catalog_id") != catalog) ||
        (!previousCatalog.is_null() && previousCatalog != catalog))
    {
        next["materials"] = Json::array();
        next.erase("material_ids");
    }
    for (const auto* field :
         {"layers", "layout_reason", "thickness_overrides", "layer_ids", "material_assignments", "z_origin_mm"})
    {
        next.erase(field);
    }
    next["source"] = source;
    next.erase("catalog_id");
    PcbSelectionData::Specification(next);
    m_specification = std::move(next);
    m_draft = draft;
    ClearReview();
    m_stage = Stage::Editing;
    m_dirty = true;
    return true;
}

void PcbSelectionModel::SetSpecification(const Json& specification)
{
    RequireEditable();
    try
    {
        PcbSelectionData::Specification(specification);
        Require(specification.at("source").is_null() || specification.at("source") == m_specification.at("source"),
                "카탈로그 적층은 현재 원문 초안의 선택을 통해 변경하십시오.");
    }
    catch (const std::exception&)
    {
        Invalidate();
        throw;
    }
    if (specification.dump() == m_specification.dump())
    {
        return;
    }
    Invalidate();
    if (specification.at("source").is_null())
    {
        m_draft = nullptr;
    }
    m_specification = specification;
}

Json PcbSelectionModel::PreviewInput() const
{
    RequireEditable();
    return Json{{"expected_revision", m_revision}, {"selection_id", m_selectionId}, {"specification", m_specification}};
}

bool PcbSelectionModel::AcceptPreview(Token token, const Json& result)
{
    if (!Matches(token, "preview"))
    {
        return false;
    }
    PcbSelectionData::Preview(result);
    Require(result.at("project_id") == m_context.at("project_id") && result.at("expected_revision") == m_revision &&
                result.at("selection_id") == m_selectionId,
            "미리보기 응답의 프로젝트 또는 기준 개정이 다릅니다.");
    Require(m_reviewedInput.dump() == PreviewInput().dump(), "미리보기 요청 이후 입력이 변경되었습니다.");
    m_preview = result;
    m_activeToken = 0;
    m_stage = Stage::Reviewed;
    return true;
}

bool PcbSelectionModel::CanApply() const
{
    return m_stage == Stage::Reviewed && m_preview.is_object() && m_preview.value("can_apply", false) &&
           m_reviewedInput.is_object() && m_reviewedInput.at("specification").dump() == m_specification.dump();
}

Json PcbSelectionModel::ApplyInput(const std::string& commandId) const
{
    Require(CanApply(), "입력과 일치하는 적용 가능한 미리보기가 필요합니다.");
    PcbSelectionData::Uuid(commandId);
    auto input = m_reviewedInput;
    input["preview_hash"] = m_preview.at("preview_hash");
    input["command_id"] = commandId;
    return input;
}

bool PcbSelectionModel::AcceptApply(Token token, const Json& result)
{
    if (!Matches(token, "apply"))
    {
        return false;
    }
    PcbSelectionData::Bounded(result);
    Require(result.is_object() && result.value("selection_id", Json(nullptr)) == m_selectionId &&
                result.value("preview_hash", Json(nullptr)) == m_preview.at("preview_hash"),
            "적용 응답이 검토한 선택과 일치하지 않습니다.");
    PcbSelectionData::Uuid(result.at("new_revision"));
    if (result.contains("project_id"))
    {
        Require(result.at("project_id") == m_context.at("project_id"), "적용 응답의 프로젝트가 다릅니다.");
    }
    m_appliedResult = result;
    m_activeToken = 0;
    m_stage = Stage::Applied;
    m_dirty = false;
    return true;
}

bool PcbSelectionModel::Fail(Token token, const Json& error)
{
    if (!IsCurrent(token))
    {
        return false;
    }
    const bool apply = m_channel == "apply";
    ClearReview();
    m_error = error;
    m_stage = apply ? Stage::Stale : Stage::Editing;
    return true;
}

const Json& PcbSelectionModel::Context() const
{
    return m_context;
}

const Json& PcbSelectionModel::Specification() const
{
    return m_specification;
}

const Json& PcbSelectionModel::SearchResult() const
{
    return m_search;
}

const Json& PcbSelectionModel::Draft() const
{
    return m_draft;
}

const Json& PcbSelectionModel::Preview() const
{
    return m_preview;
}

const Json& PcbSelectionModel::AppliedResult() const
{
    return m_appliedResult;
}

const Json& PcbSelectionModel::Error() const
{
    return m_error;
}

const std::string& PcbSelectionModel::SelectionId() const
{
    return m_selectionId;
}

const std::string& PcbSelectionModel::Revision() const
{
    return m_revision;
}

PcbSelectionModel::Stage PcbSelectionModel::CurrentStage() const
{
    return m_stage;
}

bool PcbSelectionModel::Dirty() const
{
    return m_dirty;
}

std::string PcbSelectionModel::StageName() const
{
    switch (m_stage)
    {
    case Stage::Searching:
    {
        return "searching";
    }
    case Stage::LoadingDraft:
    {
        return "loading_draft";
    }
    case Stage::Previewing:
    {
        return "previewing";
    }
    case Stage::Reviewed:
    {
        return "reviewed";
    }
    case Stage::Applying:
    {
        return "applying";
    }
    case Stage::Applied:
    {
        return "applied";
    }
    case Stage::Stale:
    {
        return "stale";
    }
    default:
    {
        return "editing";
    }
    }
}
}
