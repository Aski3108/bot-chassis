"""Модерация отзывов: согласие, очередь, одноразовые publish/reject."""

from __future__ import annotations

import uuid
from html import escape

from aiogram import F, Router, types
from aiogram.filters import Filter
from loguru import logger

from .contracts import (
    CB_REVIEW_CONSENT_NO,
    CB_REVIEW_CONSENT_YES,
    CB_REVIEW_PUBLISH_PREFIX,
    CB_REVIEW_REJECT_PREFIX,
    is_main_menu_button,
)
from .followup import PendingInput, PendingInputKind, PendingInputStore
from .keyboards import build_review_consent_keyboard, build_review_moderation_keyboard
from .ports.reviews import ReviewSinkPort
from .storage.repositories.reviews import ReviewSubmissionsRepository
from .storage.repositories.roles import RolesRepository


class ReviewActiveFilter(Filter):
    def __init__(
        self,
        store: PendingInputStore,
        domain_labels: frozenset[str] | None = None,
    ) -> None:
        self.store = store
        self.domain_labels = domain_labels or frozenset()

    async def __call__(self, message: types.Message) -> bool:
        if not message.from_user:
            return False
        if message.text and message.text.startswith("/"):
            return False
        if is_main_menu_button(message.text, domain_labels=self.domain_labels):
            self.store.clear(message.from_user.id)
            return False
        pending = self.store.get(message.from_user.id)
        return pending is not None and pending.kind in {
            PendingInputKind.REVIEW,
            PendingInputKind.REVIEW_CONSENT,
        }


def is_review_content(message: types.Message) -> bool:
    if message.photo or message.video or message.document or message.animation:
        return True
    if message.voice or message.video_note or message.audio:
        return True
    text = (message.text or message.caption or "").strip()
    return bool(text)


def create_reviews_router(
    bot_id: str,
    *,
    reviews: ReviewSubmissionsRepository,
    roles: RolesRepository,
    pending: PendingInputStore,
    review_sink: ReviewSinkPort,
    origin_bot_id: str,
    project_label: str = "Сервис",
    domain_labels: frozenset[str] | None = None,
) -> Router:
    router = Router(name="reviews")

    @router.message(ReviewActiveFilter(pending, domain_labels=domain_labels))
    async def handle_review_content(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if not is_review_content(message):
            await message.answer(
                "Нужен текст, одно медиа или медиа с подписью."
            )
            return
        pending.set(
            user_id,
            PendingInput(
                kind=PendingInputKind.REVIEW_CONSENT,
                origin_chat_id=message.chat.id,
                origin_message_id=message.message_id,
            ),
        )
        await message.answer(
            "Можно ли опубликовать этот отзыв в публичном канале?",
            reply_markup=build_review_consent_keyboard(),
        )

    @router.callback_query(F.data == CB_REVIEW_CONSENT_NO)
    async def handle_consent_no(query: types.CallbackQuery) -> None:
        user_id = query.from_user.id if query.from_user else 0
        waiting = pending.get(user_id, PendingInputKind.REVIEW_CONSENT)
        pending.clear(user_id)
        await query.answer()
        if query.message:
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        if waiting is None:
            return
        if query.message:
            await query.message.answer("Отзыв не отправлен: нет согласия на публикацию.")

    @router.callback_query(F.data == CB_REVIEW_CONSENT_YES)
    async def handle_consent_yes(query: types.CallbackQuery) -> None:
        user_id = query.from_user.id if query.from_user else 0
        waiting = pending.get(user_id, PendingInputKind.REVIEW_CONSENT)
        pending.clear(user_id)
        if waiting is None or waiting.origin_chat_id is None or waiting.origin_message_id is None:
            await query.answer("Нет отзыва для отправки", show_alert=True)
            return
        review_id = str(uuid.uuid4())
        header = (
            f"⭐ <b>Отзыв на модерацию</b>\n"
            f"<b>Проект:</b> {escape(project_label)}\n"
            f"<b>User ID:</b> <code>{user_id}</code>\n"
            f"<b>Согласие на публикацию:</b> да"
        )
        markup = build_review_moderation_keyboard(review_id)
        try:
            chat_id, message_id = await review_sink.copy_to_moderation(
                query.bot,
                header=header,
                markup=markup,
                source_chat_id=waiting.origin_chat_id,
                source_message_id=waiting.origin_message_id,
            )
        except Exception as exc:
            logger.error(f"Не удалось отправить отзыв на модерацию: {exc}")
            await query.answer("Не удалось передать отзыв", show_alert=True)
            pending.set(user_id, waiting)
            return
        await reviews.create(
            bot_id,
            review_id,
            user_id,
            origin_bot_id=origin_bot_id,
            source_chat_id=waiting.origin_chat_id,
            source_message_id=waiting.origin_message_id,
            consent_to_publish=True,
            moderation_chat_id=chat_id,
            moderation_message_id=message_id,
        )
        await query.answer("Отзыв отправлен на модерацию")
        if query.message:
            try:
                await query.message.edit_text("Спасибо. Отзыв ушёл на модерацию.")
            except Exception:
                await query.message.answer("Спасибо. Отзыв ушёл на модерацию.")

    async def _require_superadmin(query: types.CallbackQuery) -> bool:
        user_id = query.from_user.id if query.from_user else 0
        allowed = await roles.has_any_role(bot_id, user_id, ("superadmin",))
        if not allowed:
            await query.answer("Только суперадминистратор", show_alert=True)
        return allowed

    async def _drop_moderation_buttons(query: types.CallbackQuery, suffix: str) -> None:
        if query.message is None:
            return
        text = getattr(query.message, "html_text", None) or query.message.text or ""
        try:
            await query.message.edit_text(f"{text}\n\n{suffix}", parse_mode="HTML", reply_markup=None)
        except Exception:
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

    @router.callback_query(F.data.startswith(CB_REVIEW_PUBLISH_PREFIX))
    async def handle_publish(query: types.CallbackQuery) -> None:
        if not await _require_superadmin(query):
            return
        review_id = (query.data or "")[len(CB_REVIEW_PUBLISH_PREFIX):]
        record = await reviews.get(bot_id, review_id)
        if record is None:
            await query.answer("Отзыв не найден", show_alert=True)
            return
        if record.status != "pending":
            await query.answer("Уже обработано")
            return
        if not record.consent_to_publish:
            await query.answer("Нет согласия на публикацию", show_alert=True)
            return
        try:
            published = await review_sink.publish(
                query.bot,
                source_chat_id=record.source_chat_id,
                source_message_id=record.source_message_id,
            )
        except Exception as exc:
            logger.error(f"Ошибка публикации отзыва {review_id}: {exc}")
            await query.answer("Ошибка публикации", show_alert=True)
            return
        changed = await reviews.mark_published(
            bot_id,
            review_id,
            published_chat_id=published.chat_id,
            published_message_id=published.message_id,
        )
        if changed == 0:
            await query.answer("Уже обработано")
            return
        await query.answer("Опубликовано")
        await _drop_moderation_buttons(query, "✅ Опубликовано")
        try:
            await query.bot.send_message(
                chat_id=record.user_id,
                text=f"✅ Ваш отзыв опубликован: {published.url}",
            )
        except Exception as exc:
            logger.warning(f"Не удалось отправить ссылку на отзыв {review_id}: {exc}")

    @router.callback_query(F.data.startswith(CB_REVIEW_REJECT_PREFIX))
    async def handle_reject(query: types.CallbackQuery) -> None:
        if not await _require_superadmin(query):
            return
        review_id = (query.data or "")[len(CB_REVIEW_REJECT_PREFIX):]
        changed = await reviews.mark_rejected(bot_id, review_id)
        if changed == 0:
            await query.answer("Уже обработано")
            return
        await query.answer("Отклонено")
        await _drop_moderation_buttons(query, "❌ Отклонено")

    return router
