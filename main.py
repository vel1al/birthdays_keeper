import enum
import json
import datetime
import asyncio
from operator import truediv

from uuid import uuid4
from enum import Enum
from os.path import isfile

import telegram
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
from interfaces import IDataTable

class BeepInterval(enum.Enum):
    none = 0,
    hour = 1
    day = 3,
    week = 4,
    month = 5,

class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, enum.Enum):
                return {"__enum__": obj.name}
        except AttributeError:
            return None

        return json.JSONEncoder.default(self, obj)

def as_enum(entry):
    if "__enum__" in entry:
        member = entry["__enum__"]
        return getattr(BeepInterval, member)

    else:
        return entry

class JsonDataTable(IDataTable):
    def read_birthdays(self):
        with open(self._json_path + self._birthdays_file, mode="r", encoding="utf-8") as instream_b:
            self._birthdays = json.load(instream_b, object_hook=as_enum)

    def read_locals(self):
        with open(self._json_path + self._locals_file, mode="r", encoding="utf-8") as instream_l:
            self._locals = json.load(instream_l)

    def create_birthdays_json(self):
        birthdays = {'dates':{datetime.date(1945,6,22).isoformat(): '00000000-0000-0000-0000-000000000000'},
                     'birthdays': {'00000000-0000-0000-0000-000000000000':{'birthday_name': "default", 'b_is_beep_required': False, 'b_is_chat_event': False}},
                     'group_chats': {'0':{'admins_user_id': [0], 'user_list':[0]}},
                     'users_list': {0: ['00000000-0000-0000-0000-000000000000']}
                     }
        with open(self._json_path + self._birthdays_file, 'w') as ostream:
            json.dump(birthdays, ostream, cls=EnumEncoder)

    def create_locals_json(self):
        locals = {'handshake': "hello there, fellow!",
                  'invalid-state': "something fucked up, please, restart bot!"}
        with open(self._json_path + self._locals_file, 'w') as ostream:
            json.dump(locals, ostream)

    def __init__(self, birthdays_file, locals_file, json_path = ''):
        self._json_path = json_path
        self._birthdays_file = birthdays_file
        self._locals_file = locals_file

        if not isfile(self._json_path + self._birthdays_file):
            self.create_birthdays_json()
        if not isfile(self._json_path + self._locals_file):
            self.create_locals_json()

        self.read_birthdays()
        self.read_locals()

    def get_users(self):
        return self._birthdays['users_list']

    async def write_changes(self):
        with open(self._json_path + self._birthdays_file, 'w') as ostream:
            json.dump(self._birthdays, ostream, cls=EnumEncoder)

    def get_birthdays_by_id(self, target_birthday):
        if target_birthday in self._birthdays['birthdays']:
            return self._birthdays['birthdays'][target_birthday]

        return None

    def get_birthday_by_date(self, target_date):
        if target_date in self._birthdays['dates']:
            return self._birthdays['dates'][target_date]

        return None

    def get_local(self, target_local):
        if target_local in self._locals:
            return self._locals[target_local]

        return self._locals['invalid-state']

    def get_chats(self):
        return self._birthdays['group_chats']

    def get_chat_by_id(self, target_chat):
        target_chat = str(target_chat)
        if target_chat in self._birthdays['group_chats']:
            return self._birthdays['group_chats'][target_chat]

        return None

    def add_new_user(self, target_user):
        self._birthdays['users_list'][target_user] = []
    def add_new_chat(self, chat_id, chat_info):
        self._birthdays['group_chats'][chat_id] = chat_info
    def add_birthday(self, birthday, birthday_owner, date):
        birthday_uuid = str(uuid4())

        self._birthdays['birthdays'][birthday_uuid] = birthday
        self._birthdays['dates'][date] = birthday_uuid
        self._birthdays['users_list'][birthday_owner].append(birthday_uuid)
    def remove_birthday(self, target_birthday, birthday_owner):
        if target_birthday in self._birthdays['birthdays']:
            self._birthdays['birthdays'].pop(target_birthday)
            self._birthdays['users_list'][birthday_owner].remove(target_birthday)

class BirthdaysKeeper:
    def b_is_user_registered(self, target_user) -> bool:
        return target_user in self._data_table.get_users()
    def b_is_chat_registered(self, target_chat) -> bool:
        return target_chat in self._data_table.get_chats()

    def b_is_admin(self, chat_id, user_id):
        chat = self._data_table.get_chat_by_id(chat_id)
        if(chat):
            return user_id in chat['admin_user_id']

        return False

    async def reg_chat(self, target_chat: telegram.Chat, user_id = None) -> bool:
        if (target_chat.type == telegram.constants.ChatType.CHANNEL):
            return False

        chat_admins = await target_chat.get_administrators()
        if(chat_admins):
            chat_admins_ids = [chat_admin.user.id for chat_admin in chat_admins]
            chat_to_add = chat = {'admin_user_id': chat_admins_ids, 'user_list':[]}
            if(user_id):
                chat_to_add["user_list"].append(user_id)

            self._data_table.add_new_chat(chat_id=target_chat.id, chat_info=chat_to_add)
            await self._data_table.write_changes()

            return True

        return False

    async def reg_user(self, target_user: telegram.User) -> bool:
        self._data_table.add_new_user(target_user.id)
        await self._data_table.write_changes()

        return True

    async def send_message_checked(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text = None, message_local = None, reply_markup = None):
        if(not text):
            if(message_local):
                text = self._data_table.get_local(message_local)
            else:
                pass
        if (not (update.effective_chat.type == telegram.constants.ChatType.CHANNEL or update.effective_chat.type == telegram.constants.ChatType.PRIVATE)):
            await update.effective_message.reply_text(text, reply_markup=reply_markup)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup
            )

    async def collect_specific_input(self, valid_input, current_keyboard_buttons, invalid_input_local, current_local, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message_text = str.lower(update.effective_message.text)
        if(message_text in valid_input):
            return message_text

        else:
            await self.send_message_checked(update, context, invalid_input_local, reply_markup=ReplyKeyboardRemove(selective=True))
            await self.send_message_checked(update, context, current_local, reply_markup=ReplyKeyboardMarkup(
                                                              keyboard=current_keyboard_buttons,
                                                              one_time_keyboard=True,
                                                              selective=True
                                                          ))

            return None

    async def handle_reg_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if (update.effective_chat.type == telegram.constants.ChatType.PRIVATE or self.b_is_chat_registered(update.effective_chat.id)):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=self._data_table.get_local("reg-chat-twice")
            )

        if(await self.reg_chat(update.effective_chat, update.effective_user.id)):
            await update.effective_message.reply_text(self._data_table.get_local("reg-chat-success"))
        else:
            await update.effective_message.reply_text(self._data_table.get_local("reg-chat-unsupported-type"))

    async def handle_add_birthday_command_initial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if (not self.b_is_user_registered(update.effective_user.id)):
            await self.reg_user(update.effective_user)

        if (not (update.effective_chat.type == telegram.constants.ChatType.CHANNEL or update.effective_chat.type == telegram.constants.ChatType.PRIVATE)):
            if (not self.b_is_chat_registered(update.effective_chat.id)):
                await self.reg_chat(update.effective_chat, update.effective_user.id)
            if (not self.b_is_admin(update.effective_chat.id, update.effective_user.id)):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
                return ConversationHandler.END

            context.user_data['collected_birthday']= {'birthday': {'b_is_chat_event': True}, 'date': ""}
            await update.effective_message.reply_text(self._data_table.get_local("add-birthday-get-name"))
        else:
            context.user_data['collected_birthday']= {'birthday': {'b_is_chat_event': False}, 'date': ""}
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=self._data_table.get_local("add-birthday-get-name")
            )

        return 0

    async def collect_birthday_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['collected_birthday']['birthday']['birthday_name'] = update.effective_message.text
        await self.send_message_checked(update, context, message_local="add-birthday-get-date")

        return 1

    async def collect_birthday_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            date = datetime.date.fromisoformat(update.effective_message.text)
            context.user_data['collected_birthday']['date'] = date.isoformat()

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

        if(input_msg):
            context.user_data['collected_birthday']['birthday']['b_is_beep_required'] = input_msg in ["yes", "y"]

            if (context.user_data['collected_birthday']['birthday']['b_is_beep_required']):
                await self.send_message_checked(update, context, message_local="add-birthday-get-beep-interval",
                                                reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Hour", "Day", "Week", "Month"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))
                return 3
            elif (context.user_data['collected_birthday']['birthday']['b_is_chat_event']):
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
        if(input_msg):
            context.user_data['collected_birthday']['birthday']['b_is_beep_to_group_required'] = input_msg in ["yes", "y"]

            await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-required",reply_markup=ReplyKeyboardMarkup(
                                                    keyboard=[["Yes", "No"]],
                                                    one_time_keyboard=True,
                                                    selective=True
                                                ))

            return 5

        return 4

    async def collect_beep_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        input_msg = await self.collect_specific_input(
            valid_input=["hour", "h", "day", "d", "week", "w", "month", "m"],
            current_keyboard_buttons=[["Hour", "Day", "Week", "Month"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-get-beep-interval",
            update=update, context=context
        )
        if(input_msg):
            beep_interals = {"hour": BeepInterval.hour, "h": BeepInterval.hour, "day":BeepInterval.day, "d": BeepInterval.day,
                             "week": BeepInterval.week, "w": BeepInterval.week, "month": BeepInterval.month, "m": BeepInterval.month}
            context.user_data['collected_birthday']['birthday']['beep_interval'] = beep_interals[input_msg]
            if(context.user_data['collected_birthday']['birthday']['b_is_chat_event']):
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
        if (input_msg):
            context.user_data['collected_birthday']['birthday']['b_is_congrats_required'] = input_msg in ["yes", "y"]
            if(context.user_data['collected_birthday']['birthday']['b_is_congrats_required']):
                context.user_data['collected_birthday']['birthday']['congrats_target_chat'] = update.effective_chat.id
                await self.send_message_checked(update, context, message_local="add-birthday-get-target-user-id")
                return 6
            else:
                await self.ask_validate_birthday(update, context)

                return 8

        return 5

    async def collect_target_user_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['collected_birthday']['birthday']['congrats_target_user_id'] = update.effective_user.id
        await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-message")

        return 7
    async def collect_congrats_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['collected_birthday']['birthday']['congrats_message'] = update.effective_message.text

        await self.ask_validate_birthday(update, context)

        return 8

    def format_validate_birthday_message(self, collected_birthday: dict):
        birthday_name, b_is_beep_required, b_is_chat_event, date = (collected_birthday['birthday']['birthday_name'], collected_birthday['birthday']['b_is_beep_required'],
                                                                    collected_birthday['birthday']['b_is_chat_event'], collected_birthday['date'])
        beep_interval, b_is_congrats_required, b_is_beep_to_group_required, congrats_message, congrats_target_user_id = BeepInterval.none, False, False, None, None
        if(b_is_beep_required):
            beep_interval = collected_birthday['birthday']['beep_interval']
        if(b_is_chat_event):
            b_is_beep_to_group_required = collected_birthday['birthday']['b_is_beep_to_group_required']
            b_is_congrats_required = collected_birthday['birthday']['b_is_congrats_required']
        if(b_is_congrats_required):
            congrats_message = collected_birthday['birthday']['congrats_message']
            congrats_target_user_id = collected_birthday['birthday']['congrats_target_user_id']

        msg = self._data_table.get_local("add-birthday-validate-birthday-base-format").format(birthday_name, date)
        if(b_is_beep_to_group_required or b_is_beep_required):
            if(b_is_beep_required and b_is_beep_to_group_required):
                msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-both-format").format(beep_interval.name)
            elif(b_is_beep_to_group_required):
                msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-group-format").format(beep_interval.name)
            elif(b_is_beep_required):
                msg += self._data_table.get_local("add-birthday-validate-birthday-beep-to-chat-format").format(beep_interval.name)
        else:
            msg += self._data_table.get_local("add-birthday-validate-birthday-no-beep-format")
        if(b_is_congrats_required):
            msg += self._data_table.get_local("add-birthday-validate-birthday-congrats-format").format(congrats_message, congrats_target_user_id)

        return msg

    async def validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        collected_birthday = context.user_data['collected_birthday']
        input_msg = await self.collect_specific_input(
            valid_input=["add", "yes", "y", "adjust", "n", "cancel", "c"],
            current_keyboard_buttons=[["Add", "Adjust", "Cancel"]],
            invalid_input_local="add-birthday-invalid-input",
            current_local="add-birthday-validate-birthday-loop",
            update=update, context=context
        )

        if (input_msg):
            if(input_msg in ["add", "yes", "y"]):
                self._data_table.add_birthday(birthday=collected_birthday['birthday'], birthday_owner=update.effective_user.id, date=collected_birthday['date'])
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-success")
                await self._data_table.write_changes()
            elif(input_msg in ["adjust", "n"]):
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-adjust")
                return ConversationHandler.END
            else:
                await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-cancel")
                return ConversationHandler.END

        return 8

    async def ask_validate_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self.format_validate_birthday_message(context.user_data['collected_birthday'])
        await self.send_message_checked(update, context, text=msg)
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-loop",
                                        reply_markup=ReplyKeyboardMarkup(
                                            keyboard=[["Add", "Adjust", "Cancel"]],
                                            one_time_keyboard=True,
                                            selective=True
                                        ))

    async def handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_message_checked(update, context, message_local="add-birthday-validate-birthday-cancel")
        return ConversationHandler.END

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if(update.effective_chat.type == telegram.constants.ChatType.PRIVATE):
            user_id = update.effective_user.id
            if(self.b_is_user_registered(user_id)):
                await context.bot.send_message(
                    chat_id = update.effective_chat.id,
                    text = self._data_table.get_local("default-command-list")
                )
            else:
                await context.bot.send_message(
                    chat_id = update.effective_chat.id,
                    text = self._data_table.get_local("handshake")
                )
                await self.reg_user(update.effective_user)

        elif (not (update.effective_chat.type == telegram.constants.ChatType.CHANNEL)):
            if(not self.b_is_admin(update.effective_chat.id, update.effective_user.id)):
                await update.effective_message.reply_text(self._data_table.get_local("no-rights"))
            else:
                await update.effective_message.reply_text(self._data_table.get_local("reg-chat-info"))



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
                fallbacks=[CommandHandler('cancel', self.handle_start_command)]
            )
            #,CommandHandler('help', self._handle_help_command)
            #,CommandHandler('add', self._handle_add_command)
        ]
        application.add_handlers(handlers)

        #job_queue = application.job_queue
        #job_queue.run_daily(callback=self.daily_check_dialog, time=datetime.time(hour=12))

        application.run_polling()

    def __init__(self, bot_json_path, data_table: IDataTable):
        self._bot_json_path = bot_json_path
        with open(self._bot_json_path, mode="r", encoding="utf-8") as instream:
            bot_data = json.load(instream)
            self._token = bot_data.get("token", None)
            self._last_clock = bot_data.get("last_clock", 0)
            self._data_table = data_table

            if(self._token):
                self._start_bot()

if __name__ == '__main__':
    json_data_table = JsonDataTable(birthdays_file='birthdays.json', locals_file='locals.json')
    birthdays_keeper = BirthdaysKeeper(bot_json_path='bot.json', data_table=json_data_table)