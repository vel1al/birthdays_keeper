import enum
import json
import datetime

from os.path import isfile
from structs import BeepInterval, Birthday, User, GroupChat
from interfaces import IDataTable
from typing import Any

class StructsEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, enum.Enum):
                return {"__enum__": obj.name}
            elif isinstance(obj, Birthday):
                return {"__birthday__": obj.__dict__}
            elif isinstance(obj, User):
                return {"__user__": obj.__dict__}
            elif isinstance(obj, GroupChat):
                return {"__group_chat__": obj.__dict__}
            elif isinstance(obj, datetime.date):
                return {"__date__": obj.isoformat()}

        except AttributeError:
            return None

        return json.JSONEncoder.default(self, obj)


def as_struct(entry):
    if "__enum__" in entry:
        member = entry["__enum__"]
        return getattr(BeepInterval, member)
    if "__birthday__" in entry:
        return Birthday(entry["__birthday__"])
    if "__user__" in entry:
        return User(entry["__user__"])
    if "__group_chat__" in entry:
        return GroupChat(entry["__group_chat__"])
    if "__date__" in entry:
        return datetime.date.fromisoformat(entry["__date__"])

    else:
        return entry


class JsonDataTable(IDataTable):
    def read_table(self):
        with open(self._json_path + self._table_file, mode="r", encoding="utf-8") as instream_b:
            self._table = json.load(instream_b, object_hook=as_struct)

    def read_locals(self):
        with open(self._json_path + self._locals_file, mode="r", encoding="utf-8") as instream_l:
            self._locals = json.load(instream_l)

    def read_settings(self):
        with open(self._json_path + self._settings_file, mode="r", encoding="utf-8") as instream_l:
            self._settings = json.load(instream_l)

    def create_table_json(self):
        def_table = {
            'birthdays': {'00000000-0000-0000-0000-000000000000': Birthday()},
            'group_chats': {'0': GroupChat()},
            'users_list': {'0': User()}
        }

        with open(self._json_path + self._table_file, 'w') as ostream:
            json.dump(def_table, ostream, cls=StructsEncoder)

    def create_locals_json(self):
        def_locals = {
            'en': {
                'locals': {
                    "handshake-chat": "hello there, fellow!",
                    "handshake-group": "hello there, fellows!",
                    'invalid-state': "something fucked up, please, restart bot!"
                },
                'buttons': {
                    'invalid-state': [[{"text": "stop", "callback": "invalid_state"}]]
                }
            },
            "default-lang": "en"
        }

        with open(self._json_path + self._locals_file, 'w') as ostream:
            json.dump(def_locals, ostream)

    def __init__(self, table_file, locals_file, settings_file, json_path=''):
        self._settings = None
        self._locals = None
        self._table = None

        self._json_path: str = json_path
        self._table_file: str = table_file
        self._settings_file: str = settings_file
        self._locals_file: str = locals_file

        if not isfile(self._json_path + self._table_file):
            self.create_table_json()
        if not isfile(self._json_path + self._locals_file):
            self.create_locals_json()
        if not isfile(self._json_path + self._settings_file):
            exit()

        self.read_table()
        self.read_locals()
        self.read_settings()

    def b_is_user_in_table(self, user_id: str) -> bool:
        return user_id in self._table['users_list']

    def b_is_chat_in_table(self, chat_id: str) -> bool:
        return chat_id in self._table['group_chats']

    async def get_setting(self, target_setting: str) -> Any:
        if target_setting in self._settings:
            return self._settings[target_setting]

        return None

    def get_user(self, user_id: str) -> User:
        return self._table['users_list'].get(user_id, None)

    def get_chats_containing_user(self, user_id: str) -> dict[str, GroupChat]:
        output = {}
        for chat_id, chat in self._table['group_chats']:
            if user_id in chat.users_list:
                output[chat_id] = chat

        if output is not {}:
            return output
        return None

    def get_chat_by_id(self, chat_id: str) -> GroupChat:
        return self._table['group_chats'].get(chat_id, None)

    def get_chat_id_by_user_id(self, user_id) -> str:
        user = self.get_user(user_id)
        if user:
            return user.chat_id
        return None

    async def stable_changes(self) -> None:
        with open(self._json_path + self._table_file, 'w') as ostream:
            json.dump(self._table, ostream, cls=StructsEncoder)

    def get_birthday_by_id(self, birthday_id: str) -> Birthday:
        return self._table['birthdays'].get(birthday_id, None)

    def get_birthday_by_date(self, target_date: datetime.date) -> dict[str, Birthday]:
        output = {}
        for birthday_id, birthday in self._table['birthdays'].items():
            if birthday:
                if target_date == birthday.date:
                    output[birthday_id] = birthday

        return output

    def get_birthday_owner(self, birthday_id: str) -> User:
        for user_id, user in self._table['users_list'].items():
            if birthday_id in user.owning_birthdays_id:
                return user
        return None

    def get_local(self, local: str, language: str = None) -> str:
        target_lang = self._locals.get('default-lang', "en")
        if language in self._locals:
            target_lang = language

        if local in self._locals[target_lang]['locals']:
            return self._locals[target_lang]['locals'][local]

        return self._locals[target_lang]['locals']['invalid-state']

    def get_buttons(self, button: str, language: str = None) -> [[str]]:
        target_lang = self._locals.get('default-lang', "en")
        if language in self._locals:
            target_lang = language

        button_list = self._locals[target_lang]['buttons']['invalid-state']
        if button in self._locals[target_lang]['buttons']:
            buttons_list = self._locals[target_lang]['buttons'][button]

        output = [[]]
        for buttons_line in buttons_list:
            text_line = []
            for text, callback in buttons_line:
                text_line.append(text)
            output.append(text_line)

        return output

    def get_buttons_inline(self, button: str, language: str = None) -> [[dict[str, str]]]:
        target_lang = self._locals.get('default-lang', "en")
        if language in self._locals:
            target_lang = language

        if button in self._locals[target_lang]['buttons']:
            return self._locals[target_lang]['buttons'][button]

        return self._locals[target_lang]['buttons']['invalid-state']

    def add_new_user(self, user_id: str, user: User) -> None:
        self._table['users_list'][user_id] = user

    def add_new_chat(self, chat_id: str, chat: GroupChat) -> None:
        self._table['group_chats'][chat_id] = chat

    def add_user_to_chat(self, chat_id: str, user: User, user_id: str) -> bool:
        if user_id not in self._table['users_list']:
            self.add_new_user(user_id, user)

        chat = self.get_chat_by_id(chat_id)
        if chat is None:
            return False

        chat.users_list.append(user_id)
        return True
    def remove_user_from_chat(self, chat_id: str, user_id: str) -> None:
        chat = self.get_chat_by_id(chat_id)
        if chat is None:
            return

        if user_id in chat.users_list:
            chat.users_list.remove(user_id)
        if user_id in chat.admins_id:
            chat.admins_id.remove(user_id)
    def change_user_chat_status(self, chat_id: str, user_id: str, b_is_admin: bool) -> None:
        chat = self.get_chat_by_id(chat_id)
        if chat is None:
            return
        if user_id not in chat.users_list:
            return

        if b_is_admin and user_id not in chat.admins_id:
            chat.admins_id.append(user_id)
        elif  user_id in chat.admins_id:
            chat.admins_id.remove(user_id)

    def add_birthday(self, owner_id: str, birthday_id: str, birthday: Birthday):
        user = self.get_user(owner_id)
        if user:
            user.owning_birthdays_id.append(birthday_id)
            self._table['birthdays'][birthday_id] = birthday
            self.rewrite_user(owner_id, user)

    def remove_birthday(self, birthday_id: str):
        if birthday_id in self._table['birthdays']:
            self._table['birthdays'].pop(birthday_id)

        for user_id, user in self._table['users_list']:
            if birthday_id in user.owning_birthdays_id:
                self._table['users_list'][user_id].owning_birthdays.remove(birthday_id)
                break

    def adjust_birthday_field(self, birthday_id: str, field: str, value) -> None:
        birthday = self.get_birthday_by_id(birthday_id)
        if birthday:
            if hasattr(birthday, field):
                setattr(birthday, field, value)

    def adjust_user_field(self, user_id: str, field: str, value) -> None:
        user = self.get_user(user_id)
        if user:
            if hasattr(user, field):
                setattr(user, field, value)

    def rewrite_birthday(self, birthday_id: str, birthday: Birthday) -> None:
        if birthday_id in self._table['birthdays']:
            self._table['birthdays'][birthday_id] = birthday

    def rewrite_user(self, user_id: str, user: User) -> None:
        self.add_new_user(user_id, user)
