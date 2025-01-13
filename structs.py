from datetime import datetime
from abc import ABCMeta, abstractmethod
import enum
from typing import Any, Optional

"""
[r] - required, [o] - optional

birthdays.json:
-birthdays:
    -birthday_id -> uuid:
        -birthday_name -> str [r]                -name of event
        -b_is_chat_event -> bool [r]             -is birthday target is group chat    
        -date -> datetime: [r]
                                                        
        -beep_interval -> enum [o]               -interval of remind events
        -b_is_beep_required -> bool [r]          -is reminding required
        -b_is_beep_to_group_required -> bool [o] -is reminding to chat required
        
        -b_is_congrats_required -> bool [o]      -is congrats to chat required
        -congrats_target_user_id -> str [o]      -congratulations target user id                
        -congrats_message -> str [o]             -congratulations message       
                        
        -target_chat -> str [o]                  -congratulations target chat id
        
-group_chats:
    -chat_id -> str:
        -user_list -> list:
            -user_id -> str [r]

-users_list
    -user_id -> str:
        -owning_birthdays_id -> uuid [r]
        -chat_id -> str [r]

locals:
-langs -> str:
    -local_name -> str:
        -local_str -> str [r]
"""


class CollectingFieldsState:
    invalid: str = "f_invalid"
    initial: str = "f_initial"
    done: str = "f_done"
    name: str = 'f_name'
    date: str = 'f_date'
    beep_interval: str = 'f_beep_interval'
    beep: str = 'f_b_is_beep_required'
    beep_to_group: str = 'f_b_is_beep_to_group_required'
    congrats_required: str = 'f_b_is_congrats_required'
    is_chat_event : str= 'f_b_is_chat_event'
    target_chat: str = 'f_target_chat'
    congrats_target_user_id: str = 'f_congrats_target_user_id'
    congrats_msg: str = 'f_congrats_message'


class BeepInterval(enum.Enum):
    none = 0,
    day = 1,
    week = 2,
    month = 3


class BirthdayState(enum.Enum):
    valid = 0,
    appended_to_remove = 1,
    invalid_name = 2,
    invalid_date = 3,
    invalid_group_chat = 4,
    invalid_type = 5


class DefaultField:
    __metaclass__ = ABCMeta

    def __init__(self, values: dict):
        self.deserialize(values)

    def deserialize(self, values: dict) -> None:
        for attr, data in values.items():
            attr = str(attr)
            if hasattr(self, attr):
                setattr(self, attr, data)


class User(DefaultField):
    def __init__(self, values: dict = None):
        self.owning_birthdays_id: list[str] = []
        self.chat_id: str = None
        self.name: str = None

        if values:
            super().__init__(values)


class GroupChat(DefaultField):
    def __init__(self, values: dict = None):
        self.users_list: list[str] = []
        self.admins_id: list[str] = None
        self.title: str = None

        if values:
            super().__init__(values)


class Birthday(DefaultField):
    def __init__(self, values: dict = None):
        self.name: str = None
        self.date: datetime.date = None
        self.beep_interval: BeepInterval = BeepInterval.none
        self.b_is_beep_required: bool = False
        self.b_is_beep_to_group_required: bool = False
        self.b_is_congrats_required: bool = False
        self.b_is_chat_event: bool = False
        self.target_chat: str = None
        self.congrats_target_user_id: str = None
        self.congrats_message: str = None

        if values:
            self.deserialize(values)

    def deserialize(self, values: dict) -> None:
        for attr, value in values.items():
            attr = str(attr)
            if hasattr(self, attr):
                setattr(self, attr, value)

        self.validate_fields()

    def validate_fields(self) -> bool:
        if not self.b_is_beep_required:
            self.b_is_beep_required = False
            return False

        return True

    def is_fields_valid(self) -> list[BirthdayState]:
        errors = []

        if self.name is None:
            errors.append(BirthdayState.invalid_name)
        if self.date is None:
            errors.append(BirthdayState.invalid_date)
        if self.b_is_chat_event:
            if self.target_chat is None:
                errors.append(BirthdayState.invalid_group_chat)
        else:
            if self.b_is_beep_to_group_required or self.b_is_congrats_required:
                errors.append(BirthdayState.invalid_type)

        if len(errors) <= 0:
            return [BirthdayState.valid]
        else:
            return errors
