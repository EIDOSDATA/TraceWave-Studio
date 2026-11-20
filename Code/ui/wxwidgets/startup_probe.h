/** @file @brief 빈 Studio의 시작 이정표를 밝힌 뒤 계측 창을 종료한다. */
#pragma once

#include <cstdint>
#include <string>

class wxFrame;

/** @brief Windows 공통 고해상도 카운터로 첫 화면과 경량 서비스 연결을 기록한다. */
class StartupProbe final
{
public:
    explicit StartupProbe(wxFrame& frame);

    /** @brief 처음으로 보이는 2D 캔버스가 버퍼 그리기를 마친 시점이다. */
    void CanvasPainted();
    /** @brief 경량 서비스 연결 뒤 새 프로젝트 명령이 활성화된 시점이다. */
    void ServiceReady();
    /** @brief 실패를 부분 결과로 보고하고 평소 종료 경로를 따른다. */
    void Fail(const std::string& message);

private:
    void FinishIfReady();
    void Report(bool success, const std::string& message);

    wxFrame& m_frame;
    std::int64_t m_painted = 0;
    std::int64_t m_ready = 0;
    bool m_reported = false;
};
