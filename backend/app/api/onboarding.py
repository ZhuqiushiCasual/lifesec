"""初始化问卷接口 —— 冷启动（设计文档 4.1）。

    GET  /api/onboarding/questions   10 道题（前端一次拿完）
    POST /api/onboarding/preview     可审阅提案：先看"我看到的是这样"
    POST /api/onboarding/apply       确认后落盘：问卷事件 + 第一版画像

流程刻意分两步（抄 Claude Code /init）：生成 → 给人看 → 确认后才写。
预览不调模型，所以是免费、即时、可重复的。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.api import OnboardingAnswers, OnboardingApplyOut, OnboardingPreviewOut
from app.services.deps import get_current_user
from app.services.memory import onboarding

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.get("/questions")
async def get_questions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """10 道题 + 是否已经答过（前端据此决定"建立画像"入口要不要露出来）。"""
    return {"questions": onboarding.questions(), "answered": await onboarding.answered(db, user.id)}


@router.post("/preview", response_model=OnboardingPreviewOut)
async def preview(
    body: OnboardingAnswers,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingPreviewOut:
    result = await onboarding.preview(db, user, body.answers)
    return OnboardingPreviewOut(**result)


@router.post("/apply", response_model=OnboardingApplyOut)
async def apply(
    body: OnboardingAnswers,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingApplyOut:
    result = await onboarding.apply(db, user, body.answers)
    return OnboardingApplyOut(**result)
