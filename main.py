import datetime
import telegram

from uuid import uuid4
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.ext import JobQueue, ApplicationBuilder, ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
from structs import BeepInterval, BirthdayState, Birthday, User, GroupChat
from json_datatable import JsonDataTable
from interfaces import IDataTable

class BirthdaysKeeper:
    def b_is_admin(self, chat_id, user_id) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        if chat:
            return user_id in chat.admins_id

        return False

    def b_is_valid_group_chat(self, chat_type: str) -> bool:
        return not (chat_type == telegram.constants.ChatType.CHANNEL or chat_type == telegram.constants.ChatType.PRIVATE)

    def b_is_chat_registered(self, chat_id: str) -> bool:
        chat = self._data_table.get_chat_by_id(chat_id)
        return not chat is None

    def b_is_user_registered(self, user_id: str) -> bool:
        user = self._data_table.get_user(user_id)
        return not user is None

    async def reg_chat(self, target_chat: telegram.Chat, users_id: list[str] = None) -> bool:
        if not self.b_is_valid_group_chat(target_chat.type):
            return False

        chat_admins = await target_chat.get_administrators()
        if chat_admins:
            chat_admins_ids = [str(chat_admin.user.id) for chat_admin in chat_admins]
            chat_users_ids = chat_admins_ids
            if not users_id is None:
                chat_users_ids = list(set(chat_users_ids + users_id))

            chat_to_add = GroupChat({'admins_id': chat_admins_ids, 'users_list': chat_users_ids})
            self._data_table.add_new_chat(chat_id=target_chat.id, chat=chat_to_add)
            await self._data_table.stable_changes()
            return True
        return False

    async def reg_user(self, user_id: str, chat_id: str) -> None:
        self._data_table.add_new_user(user_id, User({'chat_id': chat_id, 'owning_birthdays_id': []}))
        await self._data_table.stable_changes()

    async def send_message_checked(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text = None, message_local = None, message_lang = None, reply_markup = None):
        if not text:
            if message_local:
                text = self._data_table.get_local(local=message_local, language=message_lang)
            else:
                pass

        if self.b_is_valid_group_chat(update.effective_chat.type):
            await update.effective_message.reply_text(text, reply_markup=reply_markup)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup
            )

    async def collect_specific_input(self, valid_input, current_keyboard_buttons, invalid_input_local, current_local, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message_text = str.lower(update.effective_message.text)
        if message_text in valid_input:
            return message_text

        else:
            await self.send_message_checked(update, context, invalid_input_local, reply_markup=ReplyKeyboardRemove(selective=True))
            await self.send_message_checked(update, context, current_local, reply_markup=ReplyKeyboardMarkup(
                                                              keyboard=current_keyboard_buttons,
                                                              one_time_keyboard=True,
                                                              selective=True
                                                          ))

            return None

    async def collect_birthday_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._birthdays_blanks[str(update.effective_user.id)].name = update.effective_message.text
        await self.send_message_checked(update, context, message_local="add-birthday-get-date")
        return 1

    async def collect_birthday_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            date = datetime.date.fromisoformat(update.effective_message.text)
            self._birthdays_blanks[str(update.effective_user.id)].date = date

            await self.send_message_checked(update, context, message_local="add-birthday-get-beep-to-chat-required", reply_markup=ReplyKeyboardMarkup(
                                                              keyboard=[["Yes", "No"]],
                                                              one_time_keyboard=True,
                                                              selective=True
            ))
            return 2
        except ValueError:
            await self.send_message_checked(update, context, message_local="add-birthday-get-date-iso-error")
            return 1

    async def collect_is_beep_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        input_msg = await self.collect_specific_input(
            valid_input=["yes", "y", "no", "n"],
            current_keyboard_buttons=[["Yes", "No"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-get-beep-to-chat-required",
            update=update, context=context
        )

        if input_msg:
            self._birthdays_blanks[str(update.effective_user.id)].b_is_beep_required = input_msg in ["yes", "y"]

            if self._birthdays_blanks[str(update.effective_user.id)].b_is_beep_required:
                await self.send_message_checked(update, context, message_local="add-birthday-get-beep-interval",
                                                reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Hour", "Day", "Week", "Month"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))
                return 3

            elif  self._birthdays_blanks[str(update.effective_user.id)].b_is_chat_event:
                await self.send_message_checked(update, context, message_local="add-birthday-get-beep-to-chat-required",
                                                reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Yes", "No"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))
                return 4

            else:
                await self.ask_validate_birthday(update, context)
                return 8

        return 2

    async def collect_is_beep_to_group_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        input_msg = await self.collect_specific_input(
            valid_input=["yes", "y", "no", "n"],
            current_keyboard_buttons=[["Yes", "No"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-get-beep-to-group-required",
            update=update, context=context
        )

        if input_msg:
            self._birthdays_blanks[str(update.effective_user.id)].b_is_beep_to_group_required = input_msg in ["yes", "y"]

            await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-required",reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Yes", "No"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))
            return 5

        return 4

    async def collect_beep_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        input_msg = await self.collect_specific_input(
            valid_input=["day", "d", "week", "w", "month", "m"],
            current_keyboard_buttons=[["Day", "Week", "Month"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-get-beep-interval",
            update=update, context=context
        )

        if input_msg:
            beep_intervals = {"day": BeepInterval.day, "d": BeepInterval.day,
                             "week": BeepInterval.week, "w": BeepInterval.week, "month": BeepInterval.month, "m": BeepInterval.month}
            self._birthdays_blanks[str(update.effective_user.id)].beep_interval = beep_intervals[input_msg]
            if self._birthdays_blanks[str(update.effective_user.id)].b_is_chat_event:
                await self.send_message_checked(update, context, message_local="add-birthday-get-beep-to-group-required",
                                                reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Yes", "No"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))
                return 4
            else:
                await self.ask_validate_birthday(update, context)
                return 8

        return 3

    async def collect_is_congrats_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        input_msg = await self.collect_specific_input(
            valid_input=["yes", "y", "no", "n"],
            current_keyboard_buttons=[["Yes", "No"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-get-congrats-required",
            update=update, context=context
        )

        if input_msg:
            self._birthdays_blanks[str(update.effective_user.id)].b_is_congrats_required = input_msg in ["yes", "y"]
            if self._birthdays_blanks[str(update.effective_user.id)].b_is_congrats_required:
                await self.send_message_checked(update, context, message_local="add-birthday-get-target-user-id")
                return 6
            else:
                await self.ask_validate_birthday(update, context)
                return 8

        return 5

    async def collect_target_user_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._birthdays_blanks[str(update.effective_user.id)].congrats_target_user_id = update.effective_message.text

        await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-message")
        return 7

    async def collect_congrats_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not "{name}" in update.effective_message.text:
            await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-message-invalid-format")
            return 7

        else:
            self._birthdays_blanks[str(update.effective_user.id)].congrats_message = update.effective_message.text

            await self.ask_validate_birthday(update, context)
            return 8

    def format_validate_birthday_message(self, collected_birthday: Birthday):
        msg = self._data_table.get_local("add-birthday-validate-birthday-base-format").format(collected_birthday.name, collected_birthday.date.isoformat())
        if collected_birthday.b_is_beep_required:
            #if collected_birthday.b_is_beep_to_group_required:
               # msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-both-format").format(beep_interval.name)
            if collected_birthday.b_is_beep_to_group_required:
                msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-group-format").format(collected_birthday.beep_interval.name)
            else:
                msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-chat-format").format(collected_birthday.beep_interval.name)
        else:
            msg += self._data_table.get_local("add-birthday-validate-birthday-no-beep-format")
        if collected_birthday.b_is_congrats_required:
            msg += self._data_table.get_local("add-birthday-validate-birthday-congrats-format").format(collected_birthday.congrats_message, collected_birthday.congrats_target_user_id)

        return msg

    async def validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        collected_birthday = self._birthdays_blanks[str(update.effective_user.id)]
        input_msg = await self.collect_specific_input(
            valid_input=["add", "yes", "y", "adjust", "n", "cancel", "c"],
            current_keyboard_buttons=[["Add", "Adjust", "Cancel"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-validate-birthday-loop",
            update=update, context=context
        )

        if input_msg:
            if input_msg in ["add", "yes", "y"]:
                self._data_table.add_birthday(birthday_id=str(uuid4()), birthday=self._birthdays_blanks[str(update.effective_user.id)], owner_id=str(update.effective_user.id))
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-success")
                await self._data_table.stable_changes()
            elif input_msg in ["adjust", "n"]:
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-adjust")
                return ConversationHandler.END
            else:
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-cancel")
                return ConversationHandler.END

        return 8

    async def ask_validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self.format_validate_birthday_message(self._birthdays_blanks[str(update.effective_user.id)])
        await self.send_message_checked(update, context, text=msg)
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-loop",
                                        reply_markup=ReplyKeyboardMarkup(
                                            keyboard=[["Add", "Adjust", "Cancel"]],
                                            one_time_keyboard=True,
                                            selective=True
                                        ))

    async def handle_reg_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.b_is_valid_group_chat(update.effective_chat.type) or self.b_is_chat_registered(str(update.effective_chat.id)):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=self._data_table.get_local("reg-chat-twice")
            )

        elif await self.reg_chat(update.effective_chat, [str(update.effective_user.id)]):
            await update.effective_message.reply_text(self._data_table.get_local("reg-chat-success"))
        else:
            await update.effective_message.reply_text(self._data_table.get_local("reg-chat-unsupported-type"))

    async def handle_add_birthday_command_initial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.b_is_user_registered(str(update.effective_user.id)):
            await self.reg_user(user_id=str(update.effective_user.id), chat_id=str(update.effective_chat.id))

        if self.b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_chat_registered(str(update.effective_chat.id)):
                await self.reg_chat(update.effective_chat, [str(update.effective_user.id)])
            if not self.b_is_admin(chat_id=str(update.effective_chat.id), user_id=str(update.effective_user.id)):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
                return ConversationHandler.END

            self._birthdays_blanks[str(update.effective_user.id)] = Birthday({'b_is_chat_event': True, 'target_chat': str(update.effective_chat.id)})
            await update.effective_message.reply_text(self._data_table.get_local("add-birthday-get-name"))
        else:
            self._birthdays_blanks[str(update.effective_user.id)] = Birthday({'b_is_chat_event': False})
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=self._data_table.get_local("add-birthday-get-name")
            )
        return 0

    async def handle_add_birthday_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-cancel")
        self._birthdays_blanks.pop(str(update.effective_user.id))
        return ConversationHandler.END

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
            user_id = update.effective_user.id
            if self.b_is_user_registered(user_id=str(user_id)):
                await context.bot.send_message(
                    chat_id = update.effective_chat.id,
                    text = self._data_table.get_local("default-command-list")
                )
            else:
                await context.bot.send_message(
                    chat_id = update.effective_chat.id,
                    text = self._data_table.get_local("handshake")
                )
                await self.reg_user(user_id=str(update.effective_user.id), chat_id=str(update.effective_chat.id))

        elif self.b_is_valid_group_chat(update.effective_chat.type):
            if not self.b_is_admin(chat_id=str(update.effective_chat.id), user_id=str(update.effective_user.id)):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
            else:
                if not self.b_is_chat_registered(str(update.effective_chat.id)):
                    await self.reg_chat(target_chat=update.effective_chat, users_id=[str(update.effective_user.id)])
                else:
                    await update.effective_message.reply_text(self._data_table.get_local("default-command-list"))

#    async def handle_adjust_birthday_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
#        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
#            user_id = update.effective_user.id
#            if not self.b_is_user_registered(user_id=str(user_id)):
#                await self.reg_user(user_id=str(update.effective_user.id), chat_id=str(update.effective_chat.id))
#                await self.send_message_checked(update, context, message_local="adjust-birthday-get-target-field-private",
#                                                reply_markup=ReplyKeyboardMarkup(
#                                                    keyboard=[["Name", "Date"],["Beep?", "Beep interval"]],
#                                                    one_time_keyboard=True,
#                                                    selective=True
#                                                ))
#
#        elif self.b_is_valid_group_chat(update.effective_chat.type):
#            if not self.b_is_admin(chat_id=str(update.effective_chat.id), user_id=str(update.effective_user.id)):
#                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
#            else:
#                if not self.b_is_chat_registered(str(update.effective_chat.id)):
#                    await self.reg_chat(target_chat=update.effective_chat, users_id=[str(update.effective_user.id)])
#                else:
#                    await update.effective_message.reply_text(self._data_table.get_local("default-command-list"))

#    async def adjust_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
#        input_msg = None
#        if update.effective_chat.type == telegram.constants.ChatType.PRIVATE:
#            input_msg = await self.collect_specific_input(
#                valid_input=["Name", "Date", "Beep", "Beep interval"],
#                current_keyboard_buttons=[["Add", "Adjust", "Cancel"]],
#                invalid_input_local="adjust-birthday-get-target-field-private",
#                current_local="add-birthday-validate-birthday-loop",
#                update=update, context=context
#            )
#        elif self.b_is_valid_group_chat(update.effective_chat.type):
#            input_msg = await self.collect_specific_input(
#                valid_input=["Name", "Date", "Beep", "Beep interval", "Beep to group", "Congrats", "Congrats message", "Congrats target user"],
#                current_keyboard_buttons=[["Add", "Adjust", "Cancel"]],
#                invalid_input_local="add-birthday-invalid-input",
#                current_local="adjust-birthday-get-target-field-group",
#                update=update, context=context
#            )
#        if not input_msg is None:
#            return 0
#        return 10

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

        beep_message_to_user = self._data_table.get_local("beep-to-user-format").format(birthday.name, birthday.beep_interval)
        await context.bot.send_message(
            chat_id=chat_id,
            text=beep_message_to_user,
            reply_markup=ReplyKeyboardRemove
        )

        if birthday.b_is_beep_to_group_required:
            beep_message_to_chat = self._data_table.get_local("beep-to-chat-format").format(birthday.name, birthday.beep_interval)
            await context.bot.send_message(
                chat_id=chat_id,
                text=beep_message_to_user,
                reply_markup=ReplyKeyboardRemove
            )

    async def congrats_birthday(self, context: ContextTypes.DEFAULT_TYPE, birthday: Birthday):
        await context.bot.send_message(
            chat_id=birthday.target_chat,
            text=birthday.congrats_message.format(name=birthday.congrats_target_user_id),
            reply_markup=ReplyKeyboardRemove
        )

    def _start_bot(self):
        application = ApplicationBuilder().token(self._token).build()
        handlers = [
            CommandHandler('start', self.handle_start_command),
            CommandHandler('reg_chat', self.handle_reg_chat_command),
            ConversationHandler(
                entry_points=[CommandHandler('add_birthday', self.handle_add_birthday_command_initial)],
                states={
                    0: [MessageHandler(filters=filters.ALL, callback=self.collect_birthday_name)],
                    1: [MessageHandler(filters=filters.ALL, callback=self.collect_birthday_date)],
                    2: [MessageHandler(filters=filters.ALL, callback=self.collect_is_beep_required)],
                    3: [MessageHandler(filters=filters.ALL, callback=self.collect_beep_interval)],
                    4: [MessageHandler(filters=filters.ALL, callback=self.collect_is_beep_to_group_required)],
                    5: [MessageHandler(filters=filters.ALL, callback=self.collect_is_congrats_required)],
                    6: [MessageHandler(filters=filters.ALL, callback=self.collect_target_user_id)],
                    7: [MessageHandler(filters=filters.ALL, callback=self.collect_congrats_message)],
                    8: [MessageHandler(filters=filters.ALL, callback=self.validate_birthday)]
                },
                fallbacks=[CommandHandler('cancel', self.handle_add_birthday_cancel_command)]
            )#,
            #ConversationHandler(
                #entry_points=[CommandHandler('adjust_birthday', self.handle_ajust_birthday_command)],
            #)
            #,CommandHandler('help', self._handle_help_command)
            #,CommandHandler('add', self._handle_add_command)
        ]
        application.add_handlers(handlers)

        #job_queue = application.job_queue
        #job_queue.run_daily(callback=self.birthdays_beep, time=datetime.time(hour=12))

        application.run_polling()

    def __init__(self, bot_token, data_table: IDataTable):
        self._user_locals: dict[str, str] = {}
        self._birthdays_blanks: dict[str, Birthday] = {}
        self._token = bot_token
        self._data_table = data_table

        self._start_bot()

if __name__ == '__main__':
    json_data_table = JsonDataTable(table_file='birthdays.json', locals_file='locals.json')
    birthdays_keeper = BirthdaysKeeper(bot_token="7984870379:AAFqIpOB7yDw-oHMFBe32aduJTmQpLuik6c", data_table=json_data_table)