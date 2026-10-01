"""Двусторонний мост технической поддержки Chat Listener Bridge (Button Chassis).

Ключевые свойства:
1. Связка сообщений хранится по композитному ключу (chat_id, message_id) -> user_id.
   Это исключает коллизии между разными чатами.
2. В хранилище регистрируются ОБА сообщения:
   - (support_chat_id, header_msg_id) -> user_id (карточка-шапка обращения)
   - (support_chat_id, copied_msg_id) -> user_id (копия сообщения пользователя)
   Администратор может нажать Reply на любое из них.
3. Персистентность по умолчанию включена (файл temp/support_threads.json).
   Рестарт процесса не стирает адресатов.
4. Ограничение тикетов (rate limit / max_unanswered) для защиты от спама.
5. JSON-store остаётся одноразовым: первый ответ закрывает слот.
   SQLite-store ведёт open → in_progress → closed без копирования текста.
"""

from __future__ import annotations
import inspect
import json
import os
import uuid
from html import escape
from typing import Optional
from aiogram import Bot, types
from aiogram.exceptions import TelegramForbiddenError
from loguru import logger

from .keyboards import build_operator_ticket_keyboard, build_user_ticket_reply_keyboard
from .service_notify import thread_kwargs
from .storage.sqlite_support_thread_store import TicketLimitExceeded

DEFAULT_SUPPORT_PERSISTENCE_PATH = os.path.join("temp", "support_threads.json")
_MISSING_THREAD_ID = object()
_CONTINUATION_STATUSES = {"open", "in_progress"}


class SupportThreadStore:
    """
    Хранилище соответствий между сообщениями админов и пользователями.
    Ключ: (chat_id, message_id). Значение: user_id.
    Одноразовый legacy-контракт: продолжение и reopen недоступны.
    """
    def __init__(
        self,
        persistence_file: Optional[str] = DEFAULT_SUPPORT_PERSISTENCE_PATH,
        max_active_tickets_per_user: int = 5,
    ) -> None:
        self._persistence_file = persistence_file
        self.max_active_tickets = max_active_tickets_per_user
        self.supports_continuation = False
        # {(chat_id, message_id): user_id}
        self._threads: dict[tuple[int, int], int] = {}
        # {user_id: count_of_pending_unanswered_tickets}
        self._user_ticket_counts: dict[int, int] = {}

        if self._persistence_file and os.path.exists(self._persistence_file):
            self._load()

    def _load(self) -> None:
        try:
            with open(self._persistence_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("threads", []):
                    c_id, m_id, u_id = item["chat_id"], item["message_id"], item["user_id"]
                    self._threads[(c_id, m_id)] = u_id
                self._user_ticket_counts = {int(k): v for k, v in data.get("counts", {}).items()}
        except Exception as e:
            logger.warning(f"Не удалось загрузить support threads из файла: {e}")

    def _save(self) -> None:
        if not self._persistence_file:
            return
        try:
            target_path = os.path.abspath(self._persistence_file)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            tmp_path = f"{target_path}.tmp"
            serializable = {
                "max_active_tickets": self.max_active_tickets,
                "threads": [
                    {"chat_id": c_id, "message_id": m_id, "user_id": u_id}
                    for (c_id, m_id), u_id in self._threads.items()
                ],
                "counts": {str(k): v for k, v in self._user_ticket_counts.items()},
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
        except Exception as e:
            logger.warning(f"Не удалось сохранить support threads в файл: {e}")

    def can_send_ticket(self, user_id: int) -> bool:
        """Проверяет, не превышен ли лимит неотвеченных обращений от пользователя."""
        count = self._user_ticket_counts.get(user_id, 0)
        return count < self.max_active_tickets

    def register(
        self,
        chat_id: int,
        user_id: int,
        header_msg_id: int,
        copied_msg_id: Optional[int] = None,
        ticket_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        *,
        full_name: str | None = None,
        username: str | None = None,
    ) -> None:
        """Связывает оба сообщения в админском чате с ID пользователя."""
        del ticket_id, message_thread_id, full_name, username
        self._threads[(chat_id, header_msg_id)] = user_id
        if copied_msg_id:
            self._threads[(chat_id, copied_msg_id)] = user_id

        self._user_ticket_counts[user_id] = self._user_ticket_counts.get(user_id, 0) + 1
        self._save()

    def resolve_user(self, chat_id: int, reply_to_message_id: int) -> Optional[int]:
        """Находит ID пользователя по паре (chat_id, message_id)."""
        return self._threads.get((chat_id, reply_to_message_id))

    def mark_answered(self, user_id: int) -> None:
        """Снижает счетчик активных обращений пользователя после ответа админа."""
        curr = self._user_ticket_counts.get(user_id, 0)
        if curr > 0:
            self._user_ticket_counts[user_id] = curr - 1
            self._save()


def store_supports_continuation(thread_store: object) -> bool:
    return bool(getattr(thread_store, "supports_continuation", False))


def _register_accepts_author_kwargs(register_fn: object) -> bool:
    try:
        signature = inspect.signature(register_fn)
    except (TypeError, ValueError):
        return False
    params = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return True
    return "full_name" in params and "username" in params


def operator_card_text(
    project_label: str,
    user_id: int,
    status: str,
    *,
    full_name: str | None = None,
    username: str | None = None,
) -> str:
    labels = {
        "open": "📩 Открыто",
        "in_progress": "🔄 В работе",
        "closed": "✅ Обращение обслужено",
    }
    status_line = labels.get(status, status)
    lines = [
        "📩 <b>Обращение в поддержку</b>",
        f"<b>Проект:</b> {escape(project_label)}",
    ]
    if full_name or username:
        display_name = escape(full_name) if full_name else "Пользователь"
        display_username = f"@{username}" if username else "нет username"
        lines.append(f"<b>От:</b> {display_name} ({display_username})")
    lines.append(f"<b>User ID:</b> <code>{user_id}</code>")
    lines.append("")
    lines.append(f"<b>Статус:</b> {status_line}")
    return "\n".join(lines)


async def refresh_operator_card(
    bot: Bot,
    thread_store: object,
    ticket_id: str,
    project_label: str = "Сервис",
) -> None:
    get_ticket = getattr(thread_store, "get_ticket", None)
    header_message_id = getattr(thread_store, "header_message_id", None)
    if not callable(get_ticket) or not callable(header_message_id):
        return
    ticket = get_ticket(ticket_id)
    header_id = header_message_id(ticket_id)
    if ticket is None or header_id is None or not ticket.support_chat_id:
        return
    markup = build_operator_ticket_keyboard(
        ticket_id,
        closed=ticket.ticket_status == "closed",
    )
    try:
        await bot.edit_message_text(
            chat_id=ticket.support_chat_id,
            message_id=header_id,
            text=operator_card_text(
                project_label,
                ticket.user_id,
                ticket.ticket_status,
                full_name=ticket.user_full_name,
                username=ticket.user_username,
            ),
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning(f"Не удалось обновить карточку тикета {ticket_id}: {exc}")
        try:
            await bot.edit_message_reply_markup(
                chat_id=ticket.support_chat_id,
                message_id=header_id,
                reply_markup=markup,
            )
        except Exception as markup_error:
            logger.warning(f"Не удалось снять кнопки тикета {ticket_id}: {markup_error}")


async def send_user_report_to_support(
    bot: Bot,
    support_chat_id: int,
    user_message: types.Message,
    thread_store: SupportThreadStore,
    project_label: str = "Сервис",
    message_thread_id: int | None = None,
) -> Optional[int]:
    """Доставляет обращение пользователя в чат техподдержки."""
    user = user_message.from_user
    user_id = user.id if user else 0

    if not thread_store.can_send_ticket(user_id):
        logger.warning(f"⚠️ Пользователь {user_id} превысил лимит активных тикетов без ответа.")
        return None

    username_str = f"@{user.username}" if (user and user.username) else "нет username"
    raw_full_name = user.full_name if user else None
    full_name = escape(raw_full_name or "Пользователь")
    ticket_id = str(uuid.uuid4())
    continuable = store_supports_continuation(thread_store)

    header_text = (
        f"📩 <b>Новое обращение в поддержку</b>\n"
        f"<b>Проект:</b> {escape(project_label)}\n"
        f"<b>От:</b> {full_name} ({username_str})\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<i>Для ответа нажмите 'Ответить' (Reply) на это сообщение или на копию ниже.</i>"
    )
    header_markup = (
        build_operator_ticket_keyboard(ticket_id, closed=False) if continuable else None
    )

    try:
        # 1. Карточка-шапка
        topic = thread_kwargs(message_thread_id)
        header_msg = await bot.send_message(
            chat_id=support_chat_id,
            text=header_text,
            parse_mode="HTML",
            reply_markup=header_markup,
            **topic,
        )
        # 2. Копия сообщения пользователя (текст, голос, фото, документ)
        copied_msg = await bot.copy_message(
            chat_id=support_chat_id,
            from_chat_id=user_message.chat.id,
            message_id=user_message.message_id,
            **topic,
        )

        # 3. Регистрируем ОБА сообщения по ключу (chat_id, message_id)
        register_kwargs = {
            "chat_id": support_chat_id,
            "user_id": user_id,
            "header_msg_id": header_msg.message_id,
            "copied_msg_id": copied_msg.message_id,
            "ticket_id": ticket_id,
            "message_thread_id": message_thread_id,
        }
        if _register_accepts_author_kwargs(thread_store.register):
            register_kwargs["full_name"] = raw_full_name
            register_kwargs["username"] = user.username if user else None
        try:
            thread_store.register(**register_kwargs)
        except TicketLimitExceeded:
            for message_id in (copied_msg.message_id, header_msg.message_id):
                try:
                    await bot.delete_message(chat_id=support_chat_id, message_id=message_id)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Не удалось удалить незарегистрированную карточку {message_id}: {cleanup_error}"
                    )
            logger.warning(
                f"⚠️ Лимит тикетов пользователя {user_id} сработал при атомарной регистрации."
            )
            return None
        if continuable:
            record_message = getattr(thread_store, "record_message", None)
            if callable(record_message):
                record_message(
                    ticket_id,
                    direction="user_to_support",
                    telegram_chat_id=user_message.chat.id,
                    telegram_message_id=user_message.message_id,
                    message_thread_id=None,
                )
        logger.info(f"📨 Обращение от {user_id} доставлено в {support_chat_id} (header={header_msg.message_id}, copy={copied_msg.message_id})")
        return copied_msg.message_id
    except Exception as e:
        logger.error(f"❌ Не удалось доставить обращение в поддержку: {e}")
        return None


async def send_user_followup_to_support(
    bot: Bot,
    user_message: types.Message,
    thread_store: object,
    ticket_id: str,
) -> Optional[int]:
    """Копия в существующий тикет. Лимит новых обращений не проверяется."""
    get_ticket = getattr(thread_store, "get_ticket", None)
    if not callable(get_ticket):
        return None
    ticket = get_ticket(ticket_id)
    if ticket is None:
        return None
    if ticket.origin_telegram_bot_id != bot.id:
        return None
    if ticket.ticket_status not in _CONTINUATION_STATUSES:
        return None
    topic = thread_kwargs(ticket.message_thread_id)
    try:
        copied_msg = await bot.copy_message(
            chat_id=ticket.support_chat_id,
            from_chat_id=user_message.chat.id,
            message_id=user_message.message_id,
            **topic,
        )
    except Exception as exc:
        logger.error(f"❌ Не удалось доставить продолжение тикета {ticket_id}: {exc}")
        return None
    attach_message = getattr(thread_store, "attach_message", None)
    if callable(attach_message):
        attach_message(
            ticket_id,
            chat_id=ticket.support_chat_id,
            message_id=copied_msg.message_id,
            message_role="copy",
            message_thread_id=ticket.message_thread_id,
        )
    record_message = getattr(thread_store, "record_message", None)
    if callable(record_message):
        record_message(
            ticket_id,
            direction="user_to_support",
            telegram_chat_id=user_message.chat.id,
            telegram_message_id=user_message.message_id,
            message_thread_id=None,
        )
        record_message(
            ticket_id,
            direction="user_to_support",
            telegram_chat_id=ticket.support_chat_id,
            telegram_message_id=copied_msg.message_id,
            message_thread_id=ticket.message_thread_id,
        )
    logger.info(f"📨 Продолжение тикета {ticket_id} от {ticket.user_id} доставлено.")
    return copied_msg.message_id


async def deliver_support_reply_to_user(
    bot: Bot,
    admin_reply_message: types.Message,
    thread_store: SupportThreadStore,
    support_header: str = "💬 <b>Ответ службы поддержки:</b>",
    expected_thread_id: int | None = None,
    project_label: str = "Сервис",
) -> tuple[bool, str]:
    """
    Доставляет ответ администратора пользователю в личный диалог.
    Ищет соответствие строго по (chat_id, reply_to_message_id).
    """
    replied_to = admin_reply_message.reply_to_message
    if not replied_to:
        return False, "UNKNOWN_THREAD"
    actual_thread_id = getattr(admin_reply_message, "message_thread_id", None) or None
    source_thread_id = getattr(replied_to, "message_thread_id", _MISSING_THREAD_ID)
    if source_thread_id is _MISSING_THREAD_ID:
        # Совместимость со старыми/fake Message без поля: используем настройку роутера.
        source_thread_id = expected_thread_id
    else:
        source_thread_id = source_thread_id or None
    if actual_thread_id != source_thread_id:
        return False, "WRONG_THREAD"

    resolve_ticket = getattr(thread_store, "resolve_ticket", None)
    target_ticket = None
    continuable = store_supports_continuation(thread_store)
    if callable(resolve_ticket):
        target_ticket = resolve_ticket(
            chat_id=admin_reply_message.chat.id,
            reply_to_message_id=replied_to.message_id,
        )
        if target_ticket is None:
            return False, "UNKNOWN_THREAD"
        if target_ticket.origin_telegram_bot_id != bot.id:
            return False, "FOREIGN_ORIGIN"
        stored_thread = getattr(target_ticket, "message_thread_id", None)
        if stored_thread is not None and actual_thread_id != stored_thread:
            return False, "WRONG_THREAD"
        status = getattr(target_ticket, "ticket_status", "open")
        if continuable:
            if status not in _CONTINUATION_STATUSES:
                return False, "ALREADY_ANSWERED"
            recorded = getattr(thread_store, "message_recorded", None)
            if callable(recorded) and recorded(
                admin_reply_message.chat.id,
                admin_reply_message.message_id,
            ):
                return False, "ALREADY_ANSWERED"
        elif status != "open":
            return False, "ALREADY_ANSWERED"
        target_user_id = target_ticket.user_id
    else:
        target_user_id = thread_store.resolve_user(
            chat_id=admin_reply_message.chat.id,
            reply_to_message_id=replied_to.message_id,
        )
        if not target_user_id:
            return False, "UNKNOWN_THREAD"

    reply_markup = None
    if continuable and target_ticket is not None:
        reply_markup = build_user_ticket_reply_keyboard(target_ticket.ticket_id)

    try:
        # 1. Шапка ответа
        await bot.send_message(
            chat_id=target_user_id,
            text=support_header,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        # 2. Копия ответа администратора
        copied = await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=admin_reply_message.chat.id,
            message_id=admin_reply_message.message_id,
        )
        if target_ticket is not None:
            if continuable:
                operator_id = getattr(
                    getattr(admin_reply_message, "from_user", None),
                    "id",
                    None,
                )
                attach_message = getattr(thread_store, "attach_message", None)
                if callable(attach_message):
                    attach_message(
                        target_ticket.ticket_id,
                        chat_id=admin_reply_message.chat.id,
                        message_id=admin_reply_message.message_id,
                        message_role="copy",
                        message_thread_id=actual_thread_id,
                    )
                record_message = getattr(thread_store, "record_message", None)
                if callable(record_message):
                    record_message(
                        target_ticket.ticket_id,
                        direction="support_to_user",
                        telegram_chat_id=admin_reply_message.chat.id,
                        telegram_message_id=admin_reply_message.message_id,
                        message_thread_id=actual_thread_id,
                    )
                    copied_id = getattr(copied, "message_id", None)
                    if copied_id is not None:
                        record_message(
                            target_ticket.ticket_id,
                            direction="support_to_user",
                            telegram_chat_id=target_user_id,
                            telegram_message_id=copied_id,
                            message_thread_id=None,
                        )
                mark_in_progress = getattr(thread_store, "mark_in_progress", None)
                if callable(mark_in_progress):
                    mark_in_progress(target_ticket.ticket_id, operator_id=operator_id)
                else:
                    thread_store.mark_ticket_answered(target_ticket.ticket_id)
                await refresh_operator_card(
                    bot, thread_store, target_ticket.ticket_id, project_label
                )
            else:
                thread_store.mark_ticket_answered(target_ticket.ticket_id)
        else:
            thread_store.mark_answered(target_user_id)
        logger.info(f"📬 Ответ поддержки доставлен пользователю {target_user_id}.")
        return True, "Ответ успешно доставлен пользователю."
    except TelegramForbiddenError:
        logger.warning(f"⚠️ Пользователь {target_user_id} заблокировал бота.")
        return False, "Пользователь заблокировал бота; сообщение не доставлено."
    except Exception as e:
        logger.error(f"❌ Ошибка доставки ответа поддержки пользователю {target_user_id}: {e}")
        return False, f"Ошибка отправки: {e}"
