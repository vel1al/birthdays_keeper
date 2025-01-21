import datetime
from datetime import timedelta

import telegram
import logging
from tools import b_is_valid_group_chat, dict_to_inline_keyboard, validate_input, get_cutoff

from uuid import uuid4
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardMarkup
from telegram.ext import JobQueue, ApplicationBuilder, ContextTypes, CommandHandler, ConversationHandler, \
    MessageHandler, filters, CallbackQueryHandler, CallbackContext, ChatMemberHandler
from structs import BeepInterval, CollectingFieldsState as CFS, BirthdayState, Birthday, User, GroupChat
from json_datatable import JsonDataTable
from interfaces import IDataTable

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class BirthdaysKeeper:
    def __init__(self, data_table: IDataTable):
        self._birthdays_blanks: dict[int, Birthday] = {}
        self._data_table = data_table

        self._start_bot()

    async def call_scope_function(self, update: Update, context: ContextTypes.DEFAULT_TYPE, scope_adjustment: int = 0):
        function = context.user_data['functions_map'][context.user_data['conversation_scope'] + scope_adjustment]
        context.user_data['conversation_scope'] = context.user_data['conversation_scope'] + scope_adjustment
        if function is not None:
            await function(update, context)

    def add_scope_function(self, update: Update, context: ContextTypes.DEFAULT_TYPE, function):
        scope = context.user_data['conversation_scope'] + 1
        context.user_data['conversation_scope'] = scope
        context.user_data['functions_map'][scope] = function

    def b_is_admin(self, chat_id: int, user_id: int) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        if chat:
            return user_id in chat.admins_id

        return False

    def b_is_chat_registered(self, chat_id: int) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        return chat is not None

    def b_is_user_registered(self, user_id: int) -> bool:
        user = self._data_table.get_user(user_id)
        return user is not None

    def b_is_user_registered_in_chat(self, user_id: int, chat_id: int) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        if chat is not None:
            return user_id in chat.users_list
        return False

    async def reg_chat(self, target_chat: telegram.Chat, users_id: list[int] = None) -> bool:
        if not b_is_valid_group_chat(target_chat.type):
            return False

        chat_admins = await target_chat.get_administrators()
        if chat_admins:
            chat_admins_ids = [chat_admin.user.id for chat_admin in chat_admins]
            chat_users_ids = chat_admins_ids
            title = target_chat.title
            if users_id is not None:
                chat_users_ids = list(set(chat_users_ids + users_id))

            chat_to_add = GroupChat({'admins_id': chat_admins_ids, 'users_list': chat_users_ids, 'title': title})
            self._data_table.add_new_chat(chat_id=target_chat.id, chat=chat_to_add)

            logger.info("chat %s registered", chat_to_add.__str__())

            return True

        return False

    async def reg_user(self, user: telegram.User, chat_id: int) -> None:
        user_to_add = User({'chat_id': chat_id, 'owning_birthdays_id': [], 'name': user.name, 'language': user.language_code})
        self._data_table.add_new_user(user_id=user.id, user=user_to_add)

        logger.info("user %s registered with %s id", user_to_add.__str__(), str(user.id))

    async def reg_user_to_chat(self, user: telegram.User, chat: telegram.Chat) -> bool:
        chat_member = await chat.get_member(user.id)
        if chat_member is None:
            return False

        user_to_add = User({'owning_birthdays_id': [], 'name': user.name})
        if self._data_table.add_user_to_chat(chat_id=chat.id, user_id=user.id, user=user_to_add):
            logger.info("user %s added to %s chat", str(user.id), str(chat.id))
            return True

        return False

    async def send_message_checked(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text=None,
                                   message_local=None, buttons_inline=None,
                                   b_update_msg=False):
        if text is None:
            if message_local:
                message_lang = "en"
                user = self._data_table.get_user(update.effective_user.id)
                if user is not None:
                    message_lang = user.language

                text = self._data_table.get_local(local=message_local, language=message_lang)
            else:
                pass

        if b_update_msg:
            if update.callback_query is not None:
                await update.callback_query.answer()
                if buttons_inline is not None:
                    await update.callback_query.edit_message_text(text=text,
                                                                  reply_markup=InlineKeyboardMarkup(buttons_inline))
                else:
                    await update.callback_query.edit_message_text(text=text)
            else:
                msg_id = context.user_data['last_message_id']
                if buttons_inline is not None:
                    await context.bot.edit_message_text(text=text, message_id=msg_id, chat_id=update.effective_chat.id,
                                                        reply_markup=InlineKeyboardMarkup(buttons_inline))
                else:
                    await context.bot.edit_message_text(text=text, message_id=msg_id, chat_id=update.effective_chat.id)
        else:
            msg = None
            if buttons_inline is not None:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(buttons_inline)
                )
            else:
                msg = context.user_data['last_message_id'] = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text
                )
            if msg is not None:
                context.user_data['last_message_id'] = msg.message_id

    async def ask_for_target_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not b_is_valid_group_chat(update.effective_chat.type):
            operating_birthday = self._birthdays_blanks[update.effective_user.id]
            buttons_dict = self._data_table.get_buttons_inline(button="collect-field-base")

            if operating_birthday is not None:
                if operating_birthday.b_is_beep_required:
                    if operating_birthday.b_is_chat_event:
                        buttons_dict += self._data_table.get_buttons_inline(button="collect-field-beep-group")
                    else:
                        buttons_dict += self._data_table.get_buttons_inline(button="collect-field-beep-chat")

                if operating_birthday.b_is_chat_event:
                    if operating_birthday.b_is_congrats_required:
                        buttons_dict += self._data_table.get_buttons_inline(button="collect-field-congrats-true")
                    else:
                        buttons_dict += self._data_table.get_buttons_inline(button="collect-field-congrats")

            keyboard = dict_to_inline_keyboard(buttons_dict)
            await self.send_message_checked(message_local="get-field", buttons_inline=keyboard, update=update,
                                            context=context)

    async def ask_for_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        field_locals = {CFS.name: "get-name", CFS.date: "get-date", CFS.beep: "get-beep-to-chat-required",
                        CFS.beep_to_group: "get-beep-to-group-required",
                        CFS.beep_interval: "get-beep-interval",
                        CFS.congrats_required: "get-congrats-required",
                        CFS.congrats_target_user_id: "get-target-user-id",
                        CFS.congrats_msg: "get-congrats-message"}

        bool_keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="collect-bool"))
        beep_interval_keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="collect-beep"))
        keyboards = {CFS.beep: bool_keyboard, CFS.congrats_required: bool_keyboard,
                     CFS.beep_to_group: bool_keyboard, CFS.beep_interval: beep_interval_keyboard}

        target_field = context.user_data['input_field']
        target_field_local = field_locals[target_field]
        if not context.user_data.get('b_is_input_valid'):
            target_field_local += "-invalid"

        if target_field == CFS.congrats_target_user_id:
            await self.show_users_list(update, context)

            return 4

        elif target_field == CFS.target_chat:
            await self.show_chats_list(update, context)

            return 5

        elif target_field in keyboards:
            await self.send_message_checked(message_local=target_field_local, update=update,
                                            context=context, buttons_inline=keyboards[target_field], b_update_msg=True)
        else:
            await self.send_message_checked(message_local=target_field_local, update=update,
                                            context=context, b_update_msg=True)

        return 1

    async def ask_for_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chats = context.user_data['user-chats']
        chat_id = self._birthdays_blanks[update.effective_user.id].target_chat

        if chats is None:
            return

        page = context.user_data['listing-page']

        cutoff = get_cutoff(len(chats[int(chat_id)].users_list), self.users_page_size, page)
        begin_user = 0
        if page != 0:
            begin_user = page * self.users_page_size - 1

        keyboard_dict = [[]]
        for user_id in chats[int(chat_id)].users_list[begin_user:begin_user + cutoff]:
            user = self._data_table.get_user(user_id)
            if user is not None:
                keyboard_dict.append([{"text": user.name, "callback": ("sul_select_" + str(user_id))}])
            else:
                keyboard_dict.append([{"text": user_id, "callback": ("sul_select_" + str(user_id))}])

        keyboard = dict_to_inline_keyboard(keyboard_dict)
        await self.send_message_checked(update, context, text="select_user", buttons_inline=keyboard, b_update_msg=True)

    async def ask_for_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chats = context.user_data['user-chats']

        if chats is None:
            return

        page = context.user_data['listing-page']
        keyboard_dict = [[]]

        cutoff = get_cutoff(len(chats), self.chats_page_size, page)
        begin_chat = 0
        if page != 0:
            begin_chat = page * self.chats_page_size - 1

        for chat_id, chat in dict(list(chats.items())[begin_chat:begin_chat + cutoff]).items():
            keyboard_dict.append([{"text": chat.title, "callback": ("scl_select_" + str(chat_id))}])

        keyboard = dict_to_inline_keyboard(keyboard_dict)
        await self.send_message_checked(update, context, text="select_chat", buttons_inline=keyboard, b_update_msg=True)

    async def ask_for_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = self._data_table.get_user(update.effective_user.id)
        if user is None:
            return
        birthdays = user.owning_birthdays_id

        page = context.user_data['listing-page']
        cutoff = get_cutoff(len(birthdays), self.birthdays_page_size, page)

        begin_birthday = 0
        if page != 0:
            begin_birthday = page * self.birthdays_page_size - 1

        keyboard_dict = [[]]
        for birthday_id in birthdays:
            birthday = self._data_table.get_birthday_by_id(birthday_id)
            if birthday is not None:
                keyboard_dict.append([{"text": birthday.name, "callback": ("sbl_select_" + str(birthday_id))}])

        keyboard = dict_to_inline_keyboard(keyboard_dict)
        await self.send_message_checked(update, context, text="select_birthday", buttons_inline=keyboard, b_update_msg=True)

    async def ask_for_adjusting_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['input_field'] = update.callback_query.data
        logger.info("collected field %s from %s user", update.callback_query.data, str(update.effective_user.id))

        state = await self.ask_for_field(update=update, context=context)
        if state != 1:
            return state
        return 0

    async def ask_validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self.format_validate_birthday_message(self._birthdays_blanks[update.effective_user.id])
        await self.send_message_checked(update, context, text=msg)

        keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="validate-birthday"))
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-loop",
                                        buttons_inline=keyboard)

    def format_chats_list_str(self, chats: dict[int, GroupChat], page: int) -> str:
        cutoff = get_cutoff(len(chats), self.chats_page_size, page)
        begin_chat = 0
        if page != 0:
            begin_chat = page * self.chats_page_size - 1

        msg = self._data_table.get_local("chat-list-title-format").format(page, len(chats)//self.chats_page_size)
        for chat_id, chat in dict(list(chats.items())[begin_chat:begin_chat + cutoff]).items():
            msg += self._data_table.get_local("chat-list-line-format").format(chat.title)

        return msg

    def format_users_list_str(self, chat_id: int, chat: GroupChat, page: int) -> str:
        cutoff = get_cutoff(len(chat.users_list), self.users_page_size, page)
        begin_user = 0
        if page != 0:
            begin_user = page * self.chats_page_size - 1

        msg = self._data_table.get_local("users-list-title-format").format(chat.title,page, len(chat.users_list)//self.chats_page_size)
        line_format = self._data_table.get_local("users-list-line-format")
        line_format_admin = self._data_table.get_local("users-list-line-admin-format")
        if line_format is not None:
            for user_id in chat.users_list[begin_user:begin_user + cutoff]:
                user = self._data_table.get_user(user_id)
                if user is not None:
                    if self.b_is_admin(chat_id, user_id):
                        msg += line_format_admin.format(user.name, user_id)
                    else:
                        msg += line_format.format(user.name, user_id)

        return msg

    def format_birthdays_list_str(self, user: User, page: int) -> str:
        birthdays = user.owning_birthdays_id
        cutoff = get_cutoff(len(birthdays), self.birthdays_page_size, page)
        begin_birthday = 0
        if page != 0:
            begin_birthday = page * self.birthdays_page_size - 1

        msg = self._data_table.get_local("birthdays-list-title-format").format(page, len(birthdays)//self.birthdays_page_size)
        line_format = self._data_table.get_local("birthdays-list-line-format")
        if line_format is not None:
            for birthday_id in birthdays[begin_birthday:begin_birthday + cutoff]:
                birthday = self._data_table.get_birthday_by_id(birthday_id)
                if birthday is not None:
                    msg += line_format.format(birthday.name, birthday.date)

        return msg

    async def show_chats_list_loop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chats = self._data_table.get_chats_containing_user(update.effective_user.id)
        context.user_data['user-chats'] = chats
        context.user_data['fallback-state'] = -1

        if chats is None:
            return ""

        page = context.user_data['listing-page']
        msg = self.format_chats_list_str(chats, page)

        keyboard_local = "show-chats-list"
        if len(chats) < self.chats_page_size:
            keyboard_local = "show-chats-list-one-page"
        elif page == 0:
            keyboard_local = "show-chats-list-first-page"
        else:
            diff = len(chats) - page * self.chats_page_size
            if diff < 0:
                return ""
            elif diff < self.chats_page_size:
                keyboard_local = "show-chats-list-last-page"

        keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button=keyboard_local))
        await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard)

    async def show_users_list_loop(self, update: Update, context: ContextTypes):
        chat_id = self._birthdays_blanks[update.effective_user.id].target_chat
        chat = context.user_data['user-chats'][int(chat_id)]
        context.user_data['fallback-state'] = -1

        page = context.user_data['listing-page']
        msg = self.format_users_list_str(chat_id, chat, page)

        keyboard_local = "show-users-list"
        if len(chat.users_list) < self.users_page_size:
            keyboard_local = "show-users-list-one-page"
        elif page == 0:
            keyboard_local = "show-users-list-first-page"
        else:
            diff = len(chat.users_list) - page * self.users_page_size
            if diff < 0:
                return ""
            elif diff < self.users_page_size:
                keyboard_local = "show-users-list-last-page"

        keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button=keyboard_local))
        await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard, b_update_msg=True)

    async def show_birthdays_list_loop(self, update: Update, context: ContextTypes):
        user = self._data_table.get_user(update.effective_user.id)
        if user is None:
            return

        birthday_ids = user.owning_birthdays_id
        context.user_data['fallback-state'] = -1

        page = context.user_data['listing-page']
        msg = self.format_birthdays_list_str(user, page)

        keyboard_local = "show-birthdays-list"
        if len(birthday_ids) < self.birthdays_page_size:
            keyboard_local = "show-birthdays-list-one-page"
        elif page == 0:
            keyboard_local = "show-birthdays-list-first-page"
        else:
            diff = len(birthday_ids) - page * self.birthdays_page_size
            if diff < 0:
                return ""
            elif diff < self.users_page_size:
                keyboard_local = "show-birthdays-list-last-page"

        keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline(button=keyboard_local))
        await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard, b_update_msg=True)

    async def show_birthdays_list(self, update: Update, context: ContextTypes):
        context.user_data['listing-page'] = 0
        context.user_data['inspecting_birthday'] = False
        await self.show_birthdays_list_loop(update, context)
        self.add_scope_function(update, context, self.show_birthdays_list_loop)

        return 3

    async def show_users_list(self, update: Update, context: ContextTypes):
        context.user_data['listing-page'] = 0
        await self.show_users_list_loop(update, context)
        self.add_scope_function(update, context, self.show_users_list_loop)

    async def handle_scope_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        fallback_state = context.user_data['fallback-state']

        await self.call_scope_function(update, context, -1)
        return fallback_state

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in self._birthdays_blanks:
            self._birthdays_blanks.pop(update.effective_user.id)

        await context.user_data['functions_map'][-1](update, context)
        context.user_data['conversation_scope'] = -1

        return 10

    # async def handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     self._birthdays_blanks.pop(str(update.effective_user.id))
    #     await context.user_data['functions_map'][-1]
    #
    #     return 0

    async def handle_chat_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chats = context.user_data['user-chats']
        collected_input = update.callback_query.data.replace("scl_select_", "")

        if int(collected_input) not in chats:
            await self.call_scope_function(update, context)

            return 1
        else:
            self._birthdays_blanks[update.effective_user.id].target_chat = collected_input
            await self.call_scope_function(update, context, -1)

            return -1

    async def handle_user_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._birthdays_blanks[update.effective_user.id].target_chat
        chat = context.user_data['user-chats'][int(chat_id)]
        collected_input = update.callback_query.data.replace("sul_select_", "")

        if int(collected_input) not in chat.users_list:
            await self.call_scope_function(update, context)

            return 1
        else:
            self._birthdays_blanks[update.effective_user.id].congrats_target_user_id = collected_input
            await self.call_scope_function(update, context, -1)

            return -1

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
            user_id = update.effective_user.id
            if not self.b_is_user_registered(user_id=user_id):
                await self.reg_user(user=update.effective_user, chat_id=update.effective_message.chat_id)
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=self._data_table.get_local("handshake-chat")
                )
                context.user_data['last_message_id'] = msg.message_id

            buttons_dict = self._data_table.get_buttons_inline("start")
            buttons_inline = dict_to_inline_keyboard(buttons_dict)

            await self.send_message_checked(
                update, context,
                message_local="main-conversation-loop",
                buttons_inline=buttons_inline,
            )

        elif b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_chat_registered(update.effective_chat.id):
                await self.reg_chat(target_chat=update.effective_chat, users_id=[update.effective_user.id])
            if not self.b_is_admin(chat_id=update.effective_chat.id, user_id=update.effective_user.id):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
            else:
                await self.send_message_checked(update, context, message_local="handshake-group")
                await self.send_message_checked(
                    update, context,
                    message_local="main-conversation-loop-group"
                )

        context.user_data['functions_map'] = {-1: self.menu_conv_loop}
        context.user_data['conversation_scope'] = -1

        logger.info("user %s instigate /start", str(update.effective_user.id))
        return 0

    @validate_input(["select", "s"], "scl_", 1, show_chats_list_loop)
    async def handle_select_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        context.user_data['fallback-state'] = -1

        await self.ask_for_chat(update, context)

        return 3

    @validate_input(["select", "s"], "sul_", 1, show_users_list_loop)
    async def handle_select_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        context.user_data['fallback-state'] = -1

        await self.ask_for_user(update, context)

        return 3


    @validate_input(["next", "n"], "page_", 1, show_chats_list_loop)
    async def handle_next_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        context.user_data['listing-page'] += 1
        await self.call_scope_function(update, context)

        return 1

    @validate_input(["back", "b"], "page_", 1, show_chats_list_loop)
    async def handle_back_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        page = context.user_data['listing-page']
        if page - 1 >= 0:
            context.user_data['listing-page'] -= 1

        await self.call_scope_function(update, context)

        return 1

    @validate_input(["inspect", "i"], "scl_", 1, show_chats_list_loop)
    async def handle_inspect_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        await self.ask_for_chat(update, context)
        context.user_data['listing-page'] = 0

        return 2

    async def inspect_birthday_loop(self, update, context):
        birthday_id = context.user_data['inspecting_birthday']
        if context.user_data['b_is_birthday_edited'] == False:
            birthday = self._data_table.get_birthday_by_id(int(birthday_id))

            if birthday is not None:
                msg = self.format_validate_birthday_message(birthday)
                keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline("inspect-birthday"))
                await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard, b_update_msg=True)

                self._birthdays_blanks[update.effective_user.id] = birthday

        else:
            birthday = self._birthdays_blanks[update.effective_user.id]
            self._data_table.rewrite_birthday(birthday_id, birthday)

            msg = self.format_validate_birthday_message(birthday)
            keyboard = dict_to_inline_keyboard(self._data_table.get_buttons_inline("inspect-birthday"))
            await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard,
                                            b_update_msg=True)

        return 4

    @validate_input(["inspect", "i"], "sbl_", 1, show_birthdays_list_loop)
    async def handle_inspect_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        self.add_scope_function(update, context, self.inspect_birthday_loop)
        await self.ask_for_birthday(update, context)
        context.user_data['listing-page'] = 0
        context.user_data['fallback-state'] = 2
        context.user_data['b_is_input_valid'] = True
        context.user_data['b_is_birthday_edited'] = False

        return 1

    @validate_input(["adjust", "a"], "sbl_", 1, show_birthdays_list_loop)
    async def handle_adjust_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        context.user_data['listing-page'] = 0
        context.user_data['b_is_birthday_edited'] = True

        await self.ask_for_target_field(update, context)

        return 3

    # @validate_input(["save", "s"], "sbl_", 1, show_birthdays_list_loop)
    # async def handle_save_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
    #     context.user_data['listing-page'] = 0
    #
    #     self._data_table.rewrite_birthday(context.user_data['inspecting_birthday'], self._data_table.get_birthday_by_id(context.user_data['inspecting_birthday']))
    #     await self.call_scope_function(update, context)
    #
    #     return 1

    async def handle_field_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        end_state = 1

        if not b_is_valid_group_chat(update.effective_chat.type):
            target_field = context.user_data['input_field']

            collected_input = None
            if update.message is not None:
                collected_input = update.message.text
            elif update.callback_query is not None:
                collected_input = update.callback_query.data.replace("collect_input_", "")
            if collected_input is not None:
                checked_input = None
                if target_field == CFS.beep_interval:
                    beep_intervals = {"day": BeepInterval.day, "d": BeepInterval.day,
                                      "week": BeepInterval.week, "w": BeepInterval.week, "month": BeepInterval.month,
                                      "m": BeepInterval.month}
                    checked_input = beep_intervals.get(collected_input)
                elif target_field == CFS.date:
                    try:
                        checked_input = datetime.date.fromisoformat(collected_input)
                    except ValueError:
                        pass
                elif target_field == CFS.congrats_msg:
                    if "{name}" in update.effective_message.text:
                        checked_input = collected_input
                elif target_field in [CFS.beep, CFS.beep_to_group, CFS.congrats_required]:
                    if collected_input in ["yes", "y", "no", "n"]:
                        checked_input = collected_input in ["yes", "y"]
                elif target_field in [CFS.target_chat, CFS.congrats_target_user_id]:
                    checked_input = int(collected_input)
                elif target_field != CFS.invalid:
                    checked_input = collected_input

                context.user_data['b_is_input_valid'] = checked_input is not None

                if checked_input is not None:
                    self._birthdays_blanks[update.effective_user.id].deserialize(
                        {target_field[2::]: checked_input})

                    logger.info("collected %s value to %s field", checked_input.__str__(), target_field[2::])

                    end_state = -1
                else:
                    logger.info("collected invalid %s value to %s field", collected_input.__str__(), target_field[2::])

        function = context.user_data['functions_map'][context.user_data['conversation_scope']]
        if function is not None and end_state == -1:
            return await function(update, context)
        elif end_state == 1:
            await self.ask_for_field(update, context)

        await self.call_scope_function(update, context, -1)
        return end_state

    async def handle_reg_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_chat_registered(update.effective_chat.id):
                await self.reg_chat(target_chat=update.effective_chat, users_id=[update.effective_user.id])

            elif not self.b_is_user_registered_in_chat(chat_id=update.effective_chat.id,
                                                       user_id=update.effective_user.id):
                if await self.reg_user_to_chat(chat=update.effective_chat, user=update.effective_user):
                    await self.send_message_checked(update, context, message_local="reg-user-success")
                else:
                    await self.send_message_checked(update, context, message_local="reg-user-failure")
            else:
                await self.send_message_checked(update, context, message_local="reg-user-redefinition")
        else:
            await self.send_message_checked(update, context, message_local="reg-user-invalid-chat-type")

    async def handle_chat_members_update(self, update: Update, context: CallbackContext):
        if b_is_valid_group_chat(update.chat_member.chat.type):
            chat_member_new = update.chat_member.new_chat_member
            chat_member_old = update.chat_member.old_chat_member

            if chat_member_new.status == telegram.ChatMember.LEFT:
                self._data_table.remove_user_from_chat(user_id=chat_member_new.user.id,
                                                       chat_id=update.chat_member.chat.id)
            elif chat_member_new.status == telegram.ChatMember.MEMBER:
                if chat_member_old.status == telegram.ChatMember.ADMINISTRATOR:
                    self._data_table.change_user_chat_status(user_id=chat_member_new.user.id,
                                                             chat_id=update.chat_member.chat.id, b_is_admin=False)
                else:
                    user = User({'owning_birthdays_id': [], 'name': chat_member_new.user.name})
                    self._data_table.add_user_to_chat(user_id=chat_member_new.user.id, user=user,
                                                      chat_id=update.chat_member.chat.id)
            elif chat_member_new.status == telegram.ChatMember.ADMINISTRATOR:
                self._data_table.change_user_chat_status(user_id=chat_member_new.user.id,
                                                         chat_id=update.chat_member.chat.id, b_is_admin=True)

            logger.info("user %s changed status from %s to %s in %s chat", str(chat_member_new.user.id),
                        chat_member_old.status, chat_member_new.status, str(update.chat_member.chat.id))

    async def inspect_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query is not None:
            chats = context.user_data['user-chats']
            collected_input = update.callback_query.data.replace("scl_select_", "")

            if int(collected_input) not in chats:
                await self.call_scope_function(update, context)
                return 1

            else:
                self._birthdays_blanks[update.effective_user.id].target_chat = collected_input
                await self.show_users_list(update, context)

                return 4

    async def inspect_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query is not None:
            user = self._data_table.get_user(update.effective_user.id)
            if user is not None:
                birthdays = user.owning_birthdays_id

                collected_input = update.callback_query.data.replace("sbl_select_", "")
                if int(collected_input) in birthdays:
                    context.user_data['inspecting_birthday'] = collected_input
                    await self.inspect_birthday_loop(update, context)

                    return 4

            await self.call_scope_function(update, context)
            return 1

    async def show_chats_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("user %s called /show_chats", str(update.effective_user.id))

        if b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(self._data_table.get_local("invalid-chat-type"))
            logger.info("invalid chat type for /show_chats")

            return 0

        context.user_data['listing-page'] = 0
        self.add_scope_function(update, context, self.show_chats_list_loop)
        await self.show_chats_list_loop(update, context)

        return 3

    def format_validate_birthday_message(self, collected_birthday: Birthday):
        msg = self._data_table.get_local("birthday-base-format").format(collected_birthday.name,
                                                                        collected_birthday.date.isoformat())
        if collected_birthday.b_is_beep_required:
            if collected_birthday.b_is_beep_to_group_required:
                msg += self._data_table.get_local("birthday-beep-to-both-format").format(
                    collected_birthday.beep_interval.name)
            else:
                msg += self._data_table.get_local("birthday-beep-to-chat-format").format(
                    collected_birthday.beep_interval.name)
        else:
            msg += self._data_table.get_local("birthday-no-beep-format")
        if collected_birthday.b_is_congrats_required:
            msg += self._data_table.get_local("birthday-congrats-format").format(
                collected_birthday.congrats_message, collected_birthday.congrats_target_user_id)

        return msg

    async def menu_conv_loop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
            buttons_dict = self._data_table.get_buttons_inline("start")
            buttons_inline = dict_to_inline_keyboard(buttons_dict)

            await self.send_message_checked(
                update, context,
                message_local="main-conversation-loop",
                buttons_inline=buttons_inline
            )
        elif b_is_valid_group_chat(update.effective_chat.type):
            await self.send_message_checked(
                update, context,
                message_local="main-conversation-loop-group"
            )

    async def add_birthday_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("user %s called /add_birthday_chat", str(update.effective_user.id))

        if b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(self._data_table.get_local("invalid-chat-type"))
            await self.call_scope_function(update, context)

            logger.info("invalid chat type for /add_birthday_chat")
            return 0

        if not self.b_is_user_registered(update.effective_user.id):
            await self.reg_user(user=update.effective_user, chat_id=update.effective_message.chat_id)

        self._birthdays_blanks[update.effective_user.id] = Birthday({'b_is_chat_event': False})

        context.user_data['input_field'] = CFS.initial
        self.add_scope_function(update, context, self.add_birthday_state_machine)
        await self.add_birthday_state_machine(update, context)

        return 1

    async def add_birthday_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("user %s called /add_birthday_group", str(update.effective_user.id))

        if b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(self._data_table.get_local("invalid-chat-type"))
            await self.call_scope_function(update, context)

            logger.info("invalid chat type for /add_birthday_group")
            return 0

        if not self.b_is_user_registered(update.effective_user.id):
            await self.reg_user(user=update.effective_user, chat_id=update.effective_message.chat_id)

        chats = self._data_table.get_chats_containing_user(update.effective_user.id)
        if chats is None:
            await self.send_message_checked(update, context, message_local="add-birthday-empty-chats")
            await self.call_scope_function(update, context)

            return 0

        self._birthdays_blanks[update.effective_user.id] = Birthday({'b_is_chat_event': True})

        context.user_data['input_field'] = CFS.initial
        self.add_scope_function(update, context, self.add_birthday_state_machine)
        await self.show_chats_list(update, context)

        return 2

    async def add_birthday_state_machine(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        state = context.user_data.get('input_field')

        if state is not CFS.initial:
            b_is_input_valid = context.user_data.get('b_is_input_valid')
            if not b_is_input_valid:
                await self.ask_for_field(update, context)

                logger.info("state machine - 1")
                return 1

            elif state is not CFS.invalid:
                operating_birthday = self._birthdays_blanks[update.effective_user.id]
                next_state = {CFS.name: CFS.date, CFS.date: CFS.beep}

                if operating_birthday.b_is_chat_event:
                    if operating_birthday.b_is_beep_required:
                        next_state.update({CFS.beep: CFS.beep_to_group,
                                           CFS.beep_to_group: CFS.beep_interval,
                                           CFS.beep_interval: CFS.congrats_required})
                    else:
                        next_state.update({CFS.beep: CFS.congrats_required})
                    if operating_birthday.b_is_congrats_required:
                        next_state.update({CFS.congrats_required: CFS.congrats_target_user_id,
                                           CFS.congrats_target_user_id: CFS.congrats_msg,
                                           CFS.congrats_msg: CFS.done})
                    else:
                        next_state.update({CFS.congrats_required: CFS.done})
                else:
                    if operating_birthday.b_is_beep_required:
                        next_state.update({CFS.beep: CFS.beep_interval,
                                           CFS.beep_interval: CFS.done})
                    else:
                        next_state.update({CFS.beep: CFS.done})

                if next_state[state] is not CFS.done:
                    context.user_data['input_field'] = next_state[state]
                    logger.info("user`s %s add_birthday next state - %s", str(update.effective_user.id),
                                next_state[state])

                    if next_state[state] is CFS.congrats_target_user_id:
                        await self.show_users_list(update, context)
                        return 4

                    else:
                        await self.ask_for_field(update, context)
                        return 1

                else:
                    await self.add_birthday_ask_action(update, context)
                    return 2

        elif state is CFS.initial:
            context.user_data['input_field'] = CFS.name
            context.user_data['b_is_input_valid'] = True

            await self.ask_for_field(update, context)

        return -1

    async def add_birthday_ask_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        buttons_dict = self._data_table.get_buttons_inline("add-birthday-ask-action")
        buttons_inline = dict_to_inline_keyboard(buttons_dict)

        msg = self.format_validate_birthday_message(self._birthdays_blanks[update.effective_user.id])
        await self.send_message_checked(update, context, text=msg)
        await self.send_message_checked(update, context, message_local="add-birthday-select-action",
                                        buttons_inline=buttons_inline)

        return 2

    @validate_input(["adjust"], 'ab_ac_', 2, add_birthday_ask_action)
    async def adjust_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        logger.info("user %s adjust birthday", str(update.effective_user.id))

        self.add_scope_function(update, context, self.add_birthday_ask_action)

        await self.send_message_checked(update, context, message_local="add-birthday-adjust")
        await self.ask_for_target_field(update, context)

        return 3

    def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE):
        current_jobs = context.job_queue.get_jobs_by_name(name)
        for job in current_jobs:
            job.schedule_removal()

    @validate_input(["add", "confirm", "yes", "y"], 'ab_ac_', 2, add_birthday_ask_action)
    async def confirm_add_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checked_input: str = None):
        operating_birthday = self._birthdays_blanks[update.effective_user.id]
        if BirthdayState.valid in operating_birthday.is_fields_valid():
            logger.info("user %s added birthday", str(update.effective_user.id))

            birthday_id = int(uuid4())
            owner_id = update.effective_user.id

            self._data_table.add_birthday(owner_id=owner_id, birthday_id=birthday_id,
                                          birthday=operating_birthday)

            function = context.user_data['functions_map'][-1]
            context.user_data['conversation_scope'] = -1
            await function(update, context)

            return -1

    def birthdays_to_beep(self) -> dict[int, Birthday]:
        target_date_m = datetime.datetime.now().date() + datetime.timedelta(days=30)
        target_date_w = datetime.datetime.now().date() + datetime.timedelta(days=7)
        target_date_d = datetime.datetime.now().date() + datetime.timedelta(days=1)

        birthdays_to_beep_m = self._data_table.get_birthday_by_date(target_date_m)
        birthdays_to_beep_w = self._data_table.get_birthday_by_date(target_date_w)
        birthdays_to_beep_d = self._data_table.get_birthday_by_date(target_date_d)

        return birthdays_to_beep_m | birthdays_to_beep_w | birthdays_to_beep_d

    async def birthdays_beep(self, context):
        logger.info("beeping birthdays")
        birthdays_to_beep = self.birthdays_to_beep()

        for birthday_id, birthday in birthdays_to_beep.items():
            if birthday.b_is_beep_required:
                await self.beep_birthday(context, birthday, birthday_id)
            if birthday.b_is_beep_to_group_required:
                await self.congrats_birthday(context, birthday)

    async def beep_birthday(self, context, birthday: Birthday, birthday_id: int):
        chat_id = ""
        birthday_owner = self._data_table.get_birthday_owner(birthday_id)
        if birthday_owner:
            chat_id = birthday_owner.chat_id

        beep_local = {BeepInterval.day: " tomorrow", BeepInterval.week: " in a week", BeepInterval.month: " in a month"}
        beep_message_to_user = self._data_table.get_local("beep-to-user-format").format(birthday.name, birthday.date.isoformat()) + beep_local[birthday.beep_interval]
        await context.bot.send_message(
            chat_id=chat_id,
            text=beep_message_to_user
        )

        if birthday.b_is_beep_to_group_required:
            beep_message_to_chat = self._data_table.get_local("beep-to-user-format").format(birthday.name,
                                                                                            birthday.date.isoformat()) + \
                                   beep_local[birthday.beep_interval]

            await context.bot.send_message(
                chat_id=birthday.target_chat,
                text=beep_message_to_chat
            )

    async def congrats_birthday(self, context: ContextTypes.DEFAULT_TYPE, birthday: Birthday):
        msg_user = birthday.congrats_target_user_id

        user = self._data_table.get_user(birthday.congrats_target_user_id)
        if user is not None:
            msg_user = user.name

        msg = await context.bot.send_message(
            chat_id=birthday.target_chat,
            text=birthday.congrats_message.format(name=msg_user)
        )
        context.user_data['last_message_id'] = msg.message_id

    def _start_bot(self):
        token = self._data_table.get_setting("token", None)
        if token is None:
            return

        application = ApplicationBuilder().token(token).build()
        self.chats_page_size = self._data_table.get_setting("chats_page_size", 5)
        self.users_page_size = self._data_table.get_setting("users_page_size", 5)
        self.birthdays_page_size = self._data_table.get_setting("birthdays_page_size", 5)

        #application.job_queue.run_daily(self.birthdays_beep, time=datetime.time(hour=12))
        application.job_queue.run_once(self.birthdays_beep, when=timedelta(seconds=5))

        collect_field_handlers = [
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_field_input),
            CallbackQueryHandler(self.handle_field_input, pattern="^collect_input_")
        ]

        add_birthday_action_handlers = [
            CallbackQueryHandler(self.confirm_add_birthday, pattern="^ab_ac_confirm"),
            CallbackQueryHandler(self.adjust_field, pattern="^ab_ac_adjust")
        ]

        page_control_handlers = [
            CallbackQueryHandler(self.handle_back_page, pattern="^page_back"),
            CallbackQueryHandler(self.handle_next_page, pattern="^page_next"),
        ]

        showing_chats_action_handlers = [
            CallbackQueryHandler(self.handle_inspect_chat, pattern="^scl_inspect"),
            CallbackQueryHandler(self.handle_select_chat, pattern="^scl_select"),
            *page_control_handlers
        ]

        showing_users_action_handlers = [
            CallbackQueryHandler(self.handle_select_user, pattern="^sul_select"),
            CallbackQueryHandler(self.handle_scope_back, pattern="^back"),
            *page_control_handlers
        ]

        showing_birthdays_action_handlers = [
            CallbackQueryHandler(self.handle_inspect_birthday, pattern="^sbl_inspect"),
            CallbackQueryHandler(self.handle_scope_back, pattern="^back"),
            *page_control_handlers
        ]

        inspecting_birthday_action_handlers = [
            CallbackQueryHandler(self.handle_adjust_birthday, pattern="^sbl_adjust"),
            CallbackQueryHandler(self.handle_scope_back, pattern="^back")
        ]

        showing_users_list = ConversationHandler(
            entry_points=showing_users_action_handlers,
            states={
                1: showing_users_action_handlers,
                3: [CallbackQueryHandler(self.handle_user_selection, pattern="^sul_select_")]
            },
            map_to_parent={-1: 1, 10: 10},
            fallbacks=[CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        showing_chats_list = ConversationHandler(
            entry_points=showing_chats_action_handlers,
            states={
                1: showing_chats_action_handlers,
                2: [CallbackQueryHandler(self.inspect_chat, pattern="^scl_select_")],
                3: [CallbackQueryHandler(self.handle_chat_selection, pattern="^scl_select_")],
                4: [showing_users_list]
            },
            map_to_parent={-1: 1, 10: 10},
            fallbacks=[CallbackQueryHandler(self.handle_scope_back, pattern="^back"),
                       CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        collect_field = ConversationHandler(
            entry_points=collect_field_handlers,
            states={
                1: collect_field_handlers
            },
            map_to_parent={0: 0, -1: 0, 2: 2, 4: 4},
            fallbacks=[]
        )

        adjusting_field = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.ask_for_adjusting_field, pattern="^f_")],
            states={
                0: collect_field_handlers,
                4: [showing_users_list],
                5: [showing_chats_list]
            },
            map_to_parent={-1: 1, 1: 2, 2: 2, 4: 4, 10: 10},
            fallbacks=[CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        show_birthdays  = CallbackQueryHandler(self.show_birthdays_list, pattern="sa_sbl")
        showing_birthdays = ConversationHandler(
            entry_points=showing_birthdays_action_handlers,
            states={
                2: showing_birthdays_action_handlers,
                1: [CallbackQueryHandler(self.inspect_birthday, pattern="^sbl_select_")],
                3: [adjusting_field],
                4: inspecting_birthday_action_handlers
            },
            map_to_parent={-1: 0, 10: 0},
            fallbacks=[CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        add_birthday_p = CallbackQueryHandler(self.add_birthday_chat, pattern="sa_ab_p")
        adding_birthday_p = ConversationHandler(
            entry_points=[collect_field],
            states={
                1: [collect_field],
                2: add_birthday_action_handlers,
                3: [adjusting_field]
            },
            map_to_parent={-1: 0, 10: 0},
            fallbacks=[CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        add_birthday_g = CallbackQueryHandler(self.add_birthday_group, pattern="^sa_ab_g")
        adding_birthday_g = ConversationHandler(
            entry_points=[showing_chats_list],
            states={
                1: [collect_field],
                2: add_birthday_action_handlers,
                3: [adjusting_field],
                4: [showing_users_list]
            },
            map_to_parent={-1: 0, 10: 0},
            fallbacks=[CallbackQueryHandler(self.handle_cancel, pattern="^cancel")]
        )

        select_action_handlers = [
            add_birthday_p,
            add_birthday_g,
            show_birthdays
        ]

        main_conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.handle_start_command)],
            states={
                0: select_action_handlers,
                1: [adding_birthday_p],
                2: [adding_birthday_g],
                3: [showing_birthdays]
            },
            fallbacks=[],
            conversation_timeout=120
        )

        application.add_handlers([
            main_conv,
            ChatMemberHandler(callback=self.handle_chat_members_update, chat_member_types=0),
            CommandHandler("reg_user", self.handle_reg_user_command)
        ])

        application.run_polling(
            allowed_updates=[telegram.constants.UpdateType.CHAT_MEMBER, telegram.constants.UpdateType.CALLBACK_QUERY,
                             telegram.constants.UpdateType.MESSAGE, telegram.constants.UpdateType.INLINE_QUERY])


if __name__ == '__main__':
    json_data_table = JsonDataTable(table_file='birthdays.json', locals_file='locals.json',
                                    settings_file='settings.json')
    birthdays_keeper = BirthdaysKeeper(data_table=json_data_table)
