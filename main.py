import json
import asyncio
import datetime
import enum
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, ConversationHandler

class BeepInterval(enum.Enum):
    none = 0
    day = 1
    week = 2
    month = 3

class BirthdaysKeeper():
    def read_json(self, file: str) -> dict:
        with open(file, mode="r", encoding="utf-8") as instream:
            #try:
            json_data = json.load(instream)
            #except json.decoder.JSONDecodeError:
                #json_data = ([],[])

            return json_data

    def _start_bot(self):
        application = ApplicationBuilder().token(self._token).build()
        start_handler = CommandHandler('start', self._handle_user_dialog_start)
        help_handler = CommandHandler('help', self._handle_help_command)
        #add_handler = CommandHandler('add', self._handle_add_command)
        application.add_handlers([start_handler, help_handler])

        #job_queue = application.job_queue
        #job_queue.run_daily(callback=self.daily_check_dialog, time=datetime.time(hour=12))

        application.run_polling()

    def __init__(self, data_json_path, locals_json_path, token):
        self._data_json_path = data_json_path
        self._locals_json_path = locals_json_path
        self._token = token

        self._raw_data_json = self.read_json(data_json_path)
        self._raw_locals_json = self.read_json(locals_json_path)

        self._users = self._raw_data_json[0]
        self._chats = self._raw_data_json[1]

        self._start_bot()

    #async def beep_user_dialog(event_dialog: tuple) -> None:

    #async def beep_user_chat(event_chat: tuple) -> None:

    #def b_valid_json(value) -> bool:

    async def _handle_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=self._raw_locals_json["help"])
    async def _handle_new_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=self._raw_locals_json["handshake"])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=self._raw_locals_json["help"])
        await self._adjust_data_json(file=self._data_json_path)

   # async def _handle_add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:


    async def _adjust_data_json(self, file: str) -> None:
        with open(file, mode="w", encoding="utf-8") as ostream:
            json.dump((self._users, self._chats), ostream)

    #async def handle_user_start(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:

    async def _handle_user_dialog_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if(user_id):
            stored_user = self._users.setdefault(user_id, None)
            if(not stored_user):
                await self._handle_new_user(update, context)
            else:
                await self.handle_user_start(user_id, context)


    #async def daily_check_dialog(self, context: ContextTypes.DEFAULT_TYPE) -> None:


    #def handle_user_chat_event(user, bIsJoined) -> None:

if __name__ == '__main__':
    birthdays_keeper = BirthdaysKeeper(data_json_path="birthdays.json", locals_json_path="localization.json", token='7984870379:AAFqIpOB7yDw-oHMFBe32aduJTmQpLuik6c')