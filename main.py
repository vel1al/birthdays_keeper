import datetime
import telegram
import logging

from uuid import uuid4
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
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
        self._user_locals: dict[str, str] = {}
        self._birthdays_blanks: dict[str, Birthday] = {}
        self._data_table = data_table

        self._start_bot()

    def dict_to_inline_keyboard(self, buttons: [[dict[str, str]]]) -> [[InlineKeyboardButton]]:
        output = [[]]
        for button_line in buttons:
            keyboard_line = []
            for button_dict in button_line:
                text, callback = button_dict['text'], button_dict['callback']
                keyboard_line.append(InlineKeyboardButton(text=text, callback_data=callback))
            output.append(keyboard_line)

        return output

    def b_is_admin(self, chat_id, user_id) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        if chat:
            return user_id in chat.admins_id

        return False

    def b_is_valid_group_chat(self, chat_type: str) -> bool:
        return not (
                chat_type == telegram.constants.ChatType.CHANNEL or chat_type == telegram.constants.ChatType.PRIVATE)

    def b_is_chat_registered(self, chat_id: str) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        return chat is not None

    def b_is_user_registered(self, user_id: str) -> bool:
        user = self._data_table.get_user(user_id)
        return user is not None

    def b_is_user_registered_in_chat(self, user_id: str, chat_id: str) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        if chat is not None:
            return user_id in chat.users_list
        return False

    async def reg_chat(self, target_chat: telegram.Chat, users_id: list[str] = None) -> bool:
        if not self.b_is_valid_group_chat(target_chat.type):
            return False

        chat_admins = await target_chat.get_administrators()
        if chat_admins:
            chat_admins_ids = [str(chat_admin.user.id) for chat_admin in chat_admins]
            chat_users_ids = chat_admins_ids
            if users_id is not None:
                chat_users_ids = list(set(chat_users_ids + users_id))

            chat_to_add = GroupChat({'admins_id': chat_admins_ids, 'users_list': chat_users_ids})
            self._data_table.add_new_chat(chat_id=target_chat.id, chat=chat_to_add)
            await self._data_table.stable_changes()

            logger.info("chat %s registered", chat_to_add.__str__())

            return True

        return False

    async def reg_user(self, user: telegram.User, chat_id: str) -> None:
        user_to_add = User({'chat_id': chat_id, 'owning_birthdays_id': [], 'name': user.name})
        self._data_table.add_new_user(str(user.id), user_to_add)
        await self._data_table.stable_changes()

        logger.info("user %s registered with %s id", user_to_add.__str__(), str(user.id))

    async def reg_user_to_chat(self, user: telegram.User, chat: telegram.Chat) -> bool:
        chat_member = await chat.get_member(user.id)
        if chat_member is None:
            return False

        if self._data_table.add_user_to_chat(chat_id=str(chat.id), user_id=str(user.id)):
            await self._data_table.stable_changes()

            logger.info("user %s added to %s chat", str(user.id), str(chat.id))

            return True

        return False

    async def send_message_checked(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text=None,
                                   message_local=None, message_lang=None, buttons_inline=None,
                                   b_update_msg=False):
        if not text:
            if message_local:
                text = self._data_table.get_local(local=message_local, language=message_lang)
            else:
                pass

        if not self.b_is_valid_group_chat(update.effective_chat.type):
            if b_update_msg:
                await update.callback_query.answer()
                if buttons_inline is not None:
                    await update.callback_query.edit_message_text(text=text,
                                                                  reply_markup=InlineKeyboardMarkup(buttons_inline))
                else:
                    await update.callback_query.edit_message_text(text=text)
            else:
                if buttons_inline is not None:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons_inline)
                    )
                else:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=text
                    )

    async def ask_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.b_is_valid_group_chat(update.effective_chat.type):
            operating_birthday = self._birthdays_blanks[str(update.effective_user.id)]
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

            keyboard = self.dict_to_inline_keyboard(buttons_dict)
            await self.send_message_checked(message_local="get-field", buttons_inline=keyboard, update=update,
                                            context=context)

    async def handle_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['input_field'] = update.callback_query.data
        logger.info("collected field %s from %s user", update.callback_query.data, str(update.effective_user.id))

        return await self.ask_for_input(update=update, context=context)

    async def ask_for_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.b_is_valid_group_chat(update.effective_chat.type):
            field_locals = {CFS.name: "get-name", CFS.date: "get-date", CFS.beep: "get-beep-to-chat-required",
                            CFS.beep_to_group: "get-beep-to-group-required",
                            CFS.beep_interval: "get-beep-interval",
                            CFS.congrats_required: "get-congrats-required",
                            CFS.congrats_target_user_id: "get-target-user-id",
                            CFS.congrats_msg: "get-congrats-message"}

            bool_keyboard = self.dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="collect-bool"))
            beep_interval_keyboard = self.dict_to_inline_keyboard(
                self._data_table.get_buttons_inline(button="collect-beep"))
            keyboards = {CFS.beep: bool_keyboard, CFS.congrats_required: bool_keyboard,
                         CFS.beep_to_group: bool_keyboard, CFS.beep_interval: beep_interval_keyboard}

            target_field = context.user_data['input_field']
            target_field_local = field_locals[target_field]
            if not context.user_data.get('b_is_input_valid'):
                target_field_local += "-invalid"

            if target_field in keyboards:
                await self.send_message_checked(message_local=target_field_local, update=update,
                                                context=context, buttons_inline=keyboards[target_field])
            else:
                await self.send_message_checked(message_local=target_field_local, update=update,
                                                context=context)

        return 1

    async def show_chat_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        if not self.b_is_valid_group_chat(update.effective_chat.type):
            chats = self._data_table.get_chats_containing_user(str(update.effective_user.id))
            context.user_data['user-chats'] = chats
            context.user_data['fallback-state'] = -1

            if chats is not None:
                msg = ""

                page_size = self._data_table.get_setting("chat_page_size")
                current_page, cutoff = 0, page_size
                for chat_id, chat in chats:
                    if cutoff > 0:
                        msg += self._data_table.get_local("chat-list-line-format").format(chat_id)
                        cutoff -= 1
                    else:
                        break

                keyboard = self.dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="show-chats-list"))
                await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard)

    async def handle_chat_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        fallback_state = context.user_data['fallback-state']
        if fallback_state == 1:
            await self.show_chat_list(update, context)

        return fallback_state

    async def inspect_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is not None:
            chats = context.user_data['user-chats']
            context.user_data['fallback-state'] = 1
            collected_input = update.message.text
            if collected_input not in chats:
                await self.show_chat_list(update, context)

                return 1
            else:
                chat = chats[collected_input]
                msg = self._data_table.get_local("inspect-chat-format").format(collected_input, chat.users_list,
                                                                               chat.admins_id)

                keyboard = self.dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="inspect-chat"))
                await self.send_message_checked(update, context, text=msg, buttons_inline=keyboard)

    async def handle_chat_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        collected_input = None
        if update.message is not None:
            collected_input = update.message.text
        elif update.callback_query is not None:
            collected_input = update.callback_query.data.replace("collect_input_", "")
        if collected_input is not None:
            if collected_input in ["inspect", "i"]:
                await self.send_message_checked(update, context, message_local="get-chat-id")
                return 2
            if collected_input in ["next", "n"]:
                return


    async def validate_field_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        end_state = 1

        if not self.b_is_valid_group_chat(update.effective_chat.type):
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
                elif target_field is not CFS.invalid:
                    checked_input = collected_input

                context.user_data['b_is_input_valid'] = checked_input is not None

                if checked_input is not None:
                    self._birthdays_blanks[str(update.effective_user.id)].deserialize(
                        {target_field[2::]: checked_input})
                    logger.info("collected %s value to %s field", checked_input.__str__(), target_field[2::])

                    end_state = -1
                else:
                    logger.info("collected invalid %s value to %s field", collected_input.__str__(), target_field[2::])

        functions_map = context.user_data['functions_map']
        if functions_map is not None:
            return await functions_map[end_state](update, context)

        return end_state

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

    async def ask_validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self.format_validate_birthday_message(self._birthdays_blanks[str(update.effective_user.id)])
        await self.send_message_checked(update, context, text=msg)

        keyboard = self.dict_to_inline_keyboard(self._data_table.get_buttons_inline(button="validate-birthday"))
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-loop",
                                        buttons_inline=keyboard)

    async def handle_add_birthday_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-cancel")
        self._birthdays_blanks.pop(str(update.effective_user.id))

        logger.info("user %s canceled adding birthday", str(update.effective_user.id))

        return -1

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
            user_id = update.effective_user.id
            if not self.b_is_user_registered(user_id=str(user_id)):
                await self.reg_user(user=update.effective_user, chat_id=str(update.effective_chat.id))
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=self._data_table.get_local("handshake-chat")
                )

        logger.info("user %s instigate /start", str(update.effective_user.id))
        await self.main_conv_loop(update, context)
        return 0

    async def main_conv_loop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
            buttons_dict = self._data_table.get_buttons_inline("start")
            buttons_inline = self.dict_to_inline_keyboard(buttons_dict)

            await self.send_message_checked(
                update, context,
                message_local="main-conversation-loop",
                buttons_inline=buttons_inline
            )

        elif self.b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_chat_registered(str(update.effective_chat.id)):
                await self.reg_chat(target_chat=update.effective_chat, users_id=[str(update.effective_user.id)])
            if not self.b_is_admin(chat_id=str(update.effective_chat.id), user_id=str(update.effective_user.id)):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
                logger.info("user %s dont have right in %s chat", str(update.effective_user.id),
                            str(update.effective_chat.id))
            else:
                await self.send_message_checked(update, context, message_local="handshake-group")

    async def add_birthday_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("user %s called /add_birthday_chat", str(update.effective_user.id))

        if self.b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(self._data_table.get_local("invalid-chat-type"))
            logger.info("invalid chat type for /add_birthday_chat")

            return 0

        if not self.b_is_user_registered(str(update.effective_user.id)):
            user = User({'name': update.effective_user.name})
            await self.reg_user(user=user, chat_id=str(update.effective_chat.id))

        self._birthdays_blanks[str(update.effective_user.id)] = Birthday({'b_is_chat_event': False})

        context.user_data['input_field'] = CFS.initial
        await self.add_birthday_state_machine(update, context)

        return 1

    async def add_birthday_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("user %s called /add_birthday_group", str(update.effective_user.id))

        if self.b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(self._data_table.get_local("invalid-chat-type"))
            logger.info("invalid chat type for /add_birthday_group")

            return 0

        if not self.b_is_user_registered(str(update.effective_user.id)):
            user = User({'name': update.effective_user.name})
            await self.reg_user(user=user, chat_id=str(update.effective_chat.id))

        self._birthdays_blanks[str(update.effective_user.id)] = Birthday({'b_is_chat_event': True})

        context.user_data['input_field'] = CFS.initial
        await self.ask_for_chat(update, context)

        return 2

    async def add_birthday_state_machine(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        state = context.user_data.get('input_field')

        if state is not CFS.initial:
            b_is_input_valid = context.user_data.get('b_is_input_valid')
            if not b_is_input_valid:
                await self.ask_for_input(update, context)

                logger.info("state machine - 1")
                return 1

            elif state is not CFS.invalid:
                operating_birthday = self._birthdays_blanks[str(update.effective_user.id)]
                next_state = {CFS.name: CFS.date, CFS.date: CFS.beep}

                if operating_birthday.b_is_beep_required:
                    if operating_birthday.b_is_chat_event:
                        next_state.update({CFS.beep: CFS.beep_to_group,
                                           CFS.beep_to_group: CFS.beep_interval,
                                           CFS.beep_interval: CFS.congrats_required})
                    else:
                        next_state.update({CFS.beep: CFS.beep_interval,
                                           CFS.beep_interval: CFS.done})
                elif operating_birthday.b_is_chat_event:
                    next_state.update({CFS.beep: CFS.congrats_required})
                    if operating_birthday.b_is_congrats_required:
                        next_state.update({CFS.congrats_required: CFS.congrats_target_user_id,
                                           CFS.congrats_target_user_id: CFS.congrats_msg,
                                           CFS.congrats_msg: CFS.done})
                else:
                    next_state.update({CFS.congrats_required: CFS.done})

                if next_state[state] is not CFS.done:
                    context.user_data['input_field'] = next_state[state]
                    logger.info("user`s %s add_birthday next state - %s", str(update.effective_user.id),
                                next_state[state])

                    await self.ask_for_input(update, context)

                    logger.info("state machine - 0")
                    return 0
                else:
                    await self.add_birthday_ask_action(update, context)

                    logger.info("state machine - 2")
                    return 2

        elif state is CFS.initial:
            context.user_data['input_field'] = CFS.name
            context.user_data['b_is_input_valid'] = True
            context.user_data['functions_map'] = {-1: self.add_birthday_state_machine, 1: self.ask_for_input}

            await self.ask_for_input(update, context)

        return -1

    async def add_birthday_ask_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        buttons_dict = self._data_table.get_buttons_inline("add-birthday-ask-action")
        buttons_inline = self.dict_to_inline_keyboard(buttons_dict)

        msg = self.format_validate_birthday_message(self._birthdays_blanks[str(update.effective_user.id)])
        await self.send_message_checked(update, context, text=msg)
        await self.send_message_checked(update, context, message_local="add-birthday-select-action",
                                        buttons_inline=buttons_inline)

        return 2

    async def add_birthday_action_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        valid_input = ["add", "confirm", "yes", "y", "adjust", "cancel", "n"]
        input_msg = None
        if update.message is not None:
            input_msg = update.message.text
        elif update.callback_query is not None:
            input_msg = update.callback_query.data.replace("ab_ac_", "")

        if input_msg not in valid_input:
            await self.send_message_checked(update, context, message_local="invalid-input")
            await self.add_birthday_ask_action(update, context)

            logger.info("invalid input(%s) from %s user", input_msg, str(update.effective_user.id))

            return 2

        else:
            if input_msg in ["add", "confirm", "yes"]:
                operating_birthday = self._birthdays_blanks[str(update.effective_user.id)]
                if BirthdayState.valid in operating_birthday.is_fields_valid():
                    logger.info("user %s added birthday", str(update.effective_user.id))

                    birthday_id = str(uuid4())
                    owner_id = str(update.effective_user.id)

                    self._data_table.add_birthday(owner_id=owner_id, birthday_id=birthday_id,
                                                  birthday=operating_birthday)
                    await self._data_table.stable_changes()
                    await self.send_message_checked(update, context, message_local="add-birthday-success")

                    await self.main_conv_loop(update, context)
                    context.user_data['functions_map'] = None

                    return -1

            elif input_msg in ["adjust"]:
                logger.info("user %s adjust birthday", str(update.effective_user.id))
                context.user_data['functions_map'] = {-1: self.add_birthday_ask_action, 1: self.ask_for_input}

                await self.send_message_checked(update, context, message_local="add-birthday-adjust")
                await self.ask_field(update, context)

                return 3

            else:
                logger.info("user %s cancel birthday", str(update.effective_user.id))
                context.user_data['functions_map'] = None

                self._birthdays_blanks.pop(str(update.effective_user.id))
                await self.send_message_checked(update, context, message_local="add-birthday-cancel")

                return -1

    async def handle_reg_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_chat_registered(str(update.effective_chat.id)):
                await self.reg_chat(target_chat=update.effective_chat, users_id=[str(update.effective_user.id)])
            elif not self.b_is_user_registered_in_chat(chat_id=str(update.effective_chat.id),
                                                       user_id=str(update.effective_user.id)):
                if await self.reg_user_to_chat(chat=update.effective_chat, user=update.effective_user):
                    await self.send_message_checked(update, context, message_local="reg-user-success")
                else:
                    await self.send_message_checked(update, context, message_local="reg-user-failure")

    async def handle_chat_members_update(self, update: Update, context: CallbackContext):
        if self.b_is_valid_group_chat(update.chat_member.chat.type):
            chat_member_new = update.chat_member.new_chat_member
            chat_member_old = update.chat_member.old_chat_member

            if chat_member_new.status == telegram.ChatMember.LEFT:
                self._data_table.remove_user_from_chat(user_id=str(chat_member_new.user.id),
                                                       chat_id=str(update.chat_member.chat.id))
            elif chat_member_new.status == telegram.ChatMember.MEMBER:
                if chat_member_old.status == telegram.ChatMember.ADMINISTRATOR:
                    self._data_table.change_user_chat_status(user_id=str(chat_member_new.user.id),
                                                             chat_id=str(update.chat_member.chat.id), b_is_admin=False)
                else:
                    user = User({'name': chat_member_new.user.name})
                    self._data_table.add_user_to_chat(user_id=str(chat_member_new.user.id), user=user,
                                                      chat_id=str(update.chat_member.chat.id))
            elif chat_member_new.status == telegram.ChatMember.ADMINISTRATOR:
                self._data_table.change_user_chat_status(user_id=str(chat_member_new.user.id),
                                                         chat_id=str(update.chat_member.chat.id), b_is_admin=True)

            logger.info("user %s changed status from %s to %s in %s chat", str(chat_member_new.user.id),
                        chat_member_old.status, chat_member_new.status, str(update.chat_member.chat.id))
            await self._data_table.stable_changes()

    def birthdays_to_beep(self) -> dict[str, Birthday]:
        target_date_m = datetime.datetime.now() - datetime.timedelta(days=30)
        target_date_w = datetime.datetime.now() - datetime.timedelta(days=7)
        target_date_d = datetime.datetime.now() - datetime.timedelta(days=1)

        birthdays_to_beep_m = self._data_table.get_birthday_by_date(target_date_m)
        birthdays_to_beep_w = self._data_table.get_birthday_by_date(target_date_w)
        birthdays_to_beep_d = self._data_table.get_birthday_by_date(target_date_d)

        return birthdays_to_beep_m | birthdays_to_beep_w | birthdays_to_beep_d

    async def birthdays_beep(self, context: ContextTypes.DEFAULT_TYPE):
        birthdays_to_beep = self.birthdays_to_beep()

        for birthday_id, birthday in birthdays_to_beep.items():
            if birthday.b_is_beep_required:
                await self.beep_birthday(birthday_id, birthday, birthday_id)
            if birthday.b_is_beep_to_group_required:
                await self.congrats_birthday(birthday.target_chat, birthday)

    async def beep_birthday(self, context: ContextTypes.DEFAULT_TYPE, birthday: Birthday, birthday_id: str):
        chat_id = ""
        birthday_owner = self._data_table.get_birthday_owner(birthday_id)
        if birthday_owner:
            chat_id = birthday_owner.chat_id

        beep_message_to_user = self._data_table.get_local("beep-to-user-format").format(birthday.name,
                                                                                        birthday.beep_interval)
        await context.bot.send_message(
            chat_id=chat_id,
            text=beep_message_to_user,
            reply_markup=ReplyKeyboardRemove
        )

        if birthday.b_is_beep_to_group_required:
            beep_message_to_chat = self._data_table.get_local("beep-to-chat-format").format(birthday.name,
                                                                                            birthday.beep_interval)
            await context.bot.send_message(
                chat_id=birthday.target_chat,
                text=beep_message_to_chat,
                reply_markup=ReplyKeyboardRemove
            )

    async def congrats_birthday(self, context: ContextTypes.DEFAULT_TYPE, birthday: Birthday):
        await context.bot.send_message(
            chat_id=birthday.target_chat,
            text=birthday.congrats_message.format(name=birthday.congrats_target_user_id),
            reply_markup=ReplyKeyboardRemove
        )

    async def show_birthdays_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pass

    def _start_bot(self):
        token = self._data_table.get_setting("token")
        application = ApplicationBuilder().token(token).build()

        collect_field_handlers = [
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.validate_field_input),
            CallbackQueryHandler(self.validate_field_input, pattern="^collect_input_")
        ]
        collect_field = ConversationHandler(
            entry_points=collect_field_handlers,
            states={
                1: collect_field_handlers,
            },
            map_to_parent={0: 0, -1: 0, 2: 2},
            fallbacks=[]
        )

        adjust_field = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_field, pattern="^f_")],
            states={
                1: collect_field_handlers,
            },
            map_to_parent={2: 2},
            fallbacks=[]
        )

        add_birthday_p = CallbackQueryHandler(self.add_birthday_chat, pattern="^sa_ab_")
        adding_birthday_p = ConversationHandler(
            entry_points=[collect_field],
            states={
                0: [collect_field],
                2: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_birthday_action_select),
                    CallbackQueryHandler(self.add_birthday_action_select, pattern="^ab_ac_")],
                3: [adjust_field]
            },
            map_to_parent={-1: 0},
            fallbacks=[]
        )

        add_birthday_g = CallbackQueryHandler(self.add_birthday_group, pattern="^sa_ab_asd")
        adding_birthday_g = ConversationHandler(
            entry_points=[collect_field],
            states={
                0: [collect_field],
                2: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_birthday_action_select),
                    CallbackQueryHandler(self.add_birthday_action_select, pattern="^ab_ac_asd")],
                3: [adjust_field]
            },
            map_to_parent={-1: 0},
            fallbacks=[]
        )

        # show_birthdays = CallbackQueryHandler(self.show_birthdays_list, pattern="^sa_sbl")
        # showing_birthdays = ConversationHandler(
        #     entry_points=[collecting_fields],
        #     states={
        #
        #     },
        #     map_to_parent={-1: 0},
        #     fallbacks=[]
        # )

        select_action_handlers = [
            add_birthday_p,
            #add_birthday_g,
            #show_birthdays
        ]

        main_conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.handle_start_command)],
            states={
                0: select_action_handlers,
                1: [adding_birthday_p],
                #2: [adding_birthday_g],
                #3: [showing_birthdays]
            },
            fallbacks=[]
        )

        application.add_handlers([
            main_conv,
            ChatMemberHandler(callback=self.handle_chat_members_update, chat_member_types=0),
            CommandHandler("reg_user", self.handle_reg_user_command)
        ])

        #job_queue = application.job_queue
        #job_queue.run_daily(callback=self.birthdays_beep, time=datetime.time(hour=12))

        application.run_polling(
            allowed_updates=[telegram.constants.UpdateType.CHAT_MEMBER, telegram.constants.UpdateType.CALLBACK_QUERY,
                             telegram.constants.UpdateType.MESSAGE, telegram.constants.UpdateType.INLINE_QUERY])


if __name__ == '__main__':
    json_data_table = JsonDataTable(table_file='birthdays.json', locals_file='locals.json', settings_file='settings.json')
    birthdays_keeper = BirthdaysKeeper(bot_token="7984870379:AAFqIpOB7yDw-oHMFBe32aduJTmQpLuik6c",
                                       data_table=json_data_table)
