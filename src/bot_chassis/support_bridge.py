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
"""

from __future__ import annotations
import json
import os
from html import escape
from typing import Optional, Tuple
from aiogram import Bot, types
from aiogram.exceptions import TelegramForbiddenError
from loguru import logger

DEFAULT_SUPPORT_PERSISTENCE_PATH = os.path.join("temp", "support_threads.json")


class SupportThreadStore:
    """
    Хранилище соответствий между сообщениями админов и пользователями.
    Ключ: (chat_id, message_id). Значение: user_id.
    """
    def __init__(
        self,
        persistence_file: Optional[str] = DEFAULT_SUPPORT_PERSISTENCE_PATH,
        max_active_tickets_per_user: int = 5,
    ) -> None:
        self._persistence_file = persistence_file
        self.max_active_tickets = max_active_tickets_per_user
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
    ) -> None:
        """Связывает оба сообщения в админском чате с ID пользователя."""
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


async def send_user_report_to_support(
    bot: Bot,
    support_chat_id: int,
    user_message: types.Message,
    thread_store: SupportThreadStore,
    project_label: str = "Сервис",
) -> Optional[int]:
    """Доставляет обращение пользователя в чат техподдержки."""
    user = user_message.from_user
    user_id = user.id if user else 0

    if not thread_store.can_send_ticket(user_id):
        logger.warning(f"⚠️ Пользователь {user_id} превысил лимит активных тикетов без ответа.")
        return None

    username_str = f"@{user.username}" if (user and user.username) else "нет username"
    full_name = escape(user.full_name if user else "Пользователь")

    header_text = (
        f"📩 <b>Новое обращение в поддержку</b>\n"
        f"<b>Проект:</b> {escape(project_label)}\n"
        f"<b>От:</b> {full_name} ({username_str})\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<i>Для ответа нажмите 'Ответить' (Reply) на это сообщение или на копию ниже.</i>"
    )

    try:
        # 1. Карточка-шапка
        header_msg = await bot.send_message(
            chat_id=support_chat_id,
            text=header_text,
            parse_mode="HTML",
        )
        # 2. Копия сообщения пользователя (текст, голос, фото, документ)
        copied_msg = await bot.copy_message(
            chat_id=support_chat_id,
            from_chat_id=user_message.chat.id,
            message_id=user_message.message_id,
        )

        # 3. Регистрируем ОБА сообщения по ключу (chat_id, message_id)
        thread_store.register(
            chat_id=support_chat_id,
            user_id=user_id,
            header_msg_id=header_msg.message_id,
            copied_msg_id=copied_msg.message_id,
        )
        logger.info(f"📨 Обращение от {user_id} доставлено в {support_chat_id} (header={header_msg.message_id}, copy={copied_msg.message_id})")
        return copied_msg.message_id
    except Exception as e:
        logger.error(f"❌ Не удалось доставить обращение в поддержку: {e}")
        return None


async def deliver_support_reply_to_user(
    bot: Bot,
    admin_reply_message: types.Message,
    thread_store: SupportThreadStore,
    support_header: str = "💬 <b>Ответ службы поддержки:</b>",
) -> tuple[bool, str]:
    """
    Доставляет ответ администратора пользователю в личный диалог.
    Ищет соответствие строго по (chat_id, reply_to_message_id).
    """
    replied_to = admin_reply_message.reply_to_message
    if not replied_to:
        return False, "UNKNOWN_THREAD"

    target_user_id = thread_store.resolve_user(
        chat_id=admin_reply_message.chat.id,
        reply_to_message_id=replied_to.message_id,
    )
    if not target_user_id:
        return False, "UNKNOWN_THREAD"

    try:
        # 1. Шапка ответа
        await bot.send_message(
            chat_id=target_user_id,
            text=support_header,
            parse_mode="HTML",
        )
        # 2. Копия ответа администратора
        await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=admin_reply_message.chat.id,
            message_id=admin_reply_message.message_id,
        )
        thread_store.mark_answered(target_user_id)
        logger.info(f"📬 Ответ поддержки доставлен пользователю {target_user_id}.")
        return True, "Ответ успешно доставлен пользователю."
    except TelegramForbiddenError:
        logger.warning(f"⚠️ Пользователь {target_user_id} заблокировал бота.")
        return False, "Пользователь заблокировал бота; сообщение не доставлено."
    except Exception as e:
        logger.error(f"❌ Ошибка доставки ответа поддержки пользователю {target_user_id}: {e}")
        return False, f"Ошибка отправки: {e}"
