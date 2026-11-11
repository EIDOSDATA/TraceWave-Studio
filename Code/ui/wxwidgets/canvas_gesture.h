#pragma once

/** @brief 마우스 capture를 사용하는 제스처를 서로 배타적인 상태로 관리한다. */
class CanvasGestureState final
{
public:
    enum class State
    {
        Idle,
        Selecting,
        Dragging,
        DrawingClick,
        Panning
    };

    void BeginSelection()
    {
        m_state = State::Selecting;
    }

    void BeginDrawing()
    {
        m_state = State::DrawingClick;
    }

    void BeginPan()
    {
        m_state = State::Panning;
    }

    /** @brief 선택 중인 물체만 이동으로 전환하고 다른 입력 상태의 승격은 거절한다. */
    bool BeginDrag()
    {
        if (!Selecting())
        {
            return false;
        }
        m_state = State::Dragging;
        return true;
    }

    void Reset()
    {
        m_state = State::Idle;
    }

    bool Selecting() const
    {
        return m_state == State::Selecting || m_state == State::Dragging;
    }

    bool Dragging() const
    {
        return m_state == State::Dragging;
    }

    bool DrawingClick() const
    {
        return m_state == State::DrawingClick;
    }

    bool Panning() const
    {
        return m_state == State::Panning;
    }

    bool Active() const
    {
        return m_state != State::Idle;
    }

private:
    State m_state = State::Idle;
};
