"""
[r] - required, [o] - optional

birthdays.json:
-dates:
    -date -> datetime:
        -birthday_id -> uuid [r]            -birthday date
-birthdays:
    -birthday_id -> uuid:
        -birthday_name -> str [r]                -name of event
        -beep_intervals -> enum [o]              -interval of remind events
        -b_is_beep_required -> bool [r]          -is reminding required
        -b_is_beep_to_group_required -> bool [o] -reminding chat id
        -b_is_chat_event -> bool [r]             -is birthday target is group chat
        -congrats_target_chat -> str [o]         -congratulations target chat id
        -congrats_target_user_id -> str [o]      -congratulations target user id
        -congrats_message -> str [o]             -congratulations message
-group_chats:
    -chat_id -> str:
        -user_list -> list:
            -user_id -> str [r]
-users_list
    -user_id -> str:
        -owning_birthday_id -> uuid [r]

locals:
-local_name -> str:
    -local_str -> str [r]
"""

from abc import ABCMeta, abstractmethod

class IDataTable:
    __metaclass__ = ABCMeta

    @classmethod
    @abstractmethod
    async def write_changes(self):
        pass

    @classmethod
    @abstractmethod
    def get_users(self):
        pass
    @classmethod
    @abstractmethod
    def get_birthdays_by_id(self, target_birthday):
        pass
    @classmethod
    @abstractmethod
    def get_birthday_by_date(self, target_date):
        pass
    @classmethod
    @abstractmethod
    def get_local(self, target_local):
        pass
    @classmethod
    @abstractmethod
    def get_chats(self):
        pass
    @classmethod
    @abstractmethod
    def get_chat_by_id(self, target_chat):
        pass

    @classmethod
    @abstractmethod
    def add_new_user(self, target_user):
        pass
    @classmethod
    @abstractmethod
    def add_new_chat(self, chat_id, chat_info):
        pass
    @classmethod
    @abstractmethod
    def add_birthday(self, birthday, birthday_owner, date):
        pass
    @classmethod
    @abstractmethod
    def remove_birthday(self, target_birthday, birthday_owner):
        pass