from abc import ABCMeta, abstractmethod
from datetime import datetime
from structs import Birthday, User, GroupChat
from typing import Any, Optional

class IDataTable:
    __metaclass__ = ABCMeta

    @classmethod
    @abstractmethod
    def add_new_chat(self, chat_id: int, chat: GroupChat) -> None:
        pass
    @classmethod
    @abstractmethod
    def add_user_to_chat(self, chat_id: int, user_id: int, user: User = None) -> bool:
        pass
    @classmethod
    @abstractmethod
    def remove_user_from_chat(self, chat_id: int, user_id: int) -> None:
        pass
    @classmethod
    @abstractmethod
    def change_user_chat_status(self, chat_id: int, user_id: int, b_is_admin: bool) -> None:
        pass
    @classmethod
    @abstractmethod
    def get_chats_containing_user(self, user_id: int) -> dict[int, GroupChat]:
        pass
    @classmethod
    @abstractmethod
    def get_chat_by_id(self, chat_id: int) -> GroupChat:
        pass
    @classmethod
    @abstractmethod
    def get_chat_id_by_user_id(self, user_id: int) -> int:
        pass

    @classmethod
    @abstractmethod
    def get_local(self, local: str, language: str) -> str:
        pass
    @classmethod
    @abstractmethod
    def get_buttons(self, button: str, language: str) -> [[str]]:
        pass
    @classmethod
    @abstractmethod
    def get_buttons_inline(self, button: str, language: str) -> [[(str, str)]]:
        pass
    @classmethod
    @abstractmethod
    def get_setting(self, target_setting: str, hard_def: Any) -> Any:
        pass

    @classmethod
    @abstractmethod
    def add_new_user(self, user_id: int, user: User) -> None:
        pass
    @classmethod
    @abstractmethod
    def get_user(self, user_id: int) -> User:
        pass
    @classmethod
    @abstractmethod
    def adjust_user_field(self, user_id: int, field: str, value) -> None:
        pass
    @classmethod
    @abstractmethod
    def rewrite_user(self, user_id: int, user: User) -> None:
        pass

    @classmethod
    @abstractmethod
    def add_birthday(self, owner_id: int, birthday_id: int, birthday: Birthday) -> None:
        pass
    @classmethod
    @abstractmethod
    def remove_birthday(self, birthday_id: int) -> None:
        pass
    @classmethod
    @abstractmethod
    def rewrite_birthday(self, birthday_id: int, birthday: Birthday) -> None:
        pass
    @classmethod
    @abstractmethod
    def adjust_birthday_field(self, birthday_id: int, field: str, value) -> None:
        pass
    @classmethod
    @abstractmethod
    def get_birthday_by_id(self, birthday_id: int) -> Birthday:
        pass
    @classmethod
    @abstractmethod
    def get_birthday_by_date(self, date: datetime) -> dict[int, Birthday]:
        pass
    @classmethod
    @abstractmethod
    def get_birthday_owner(self, birthday_id: int) -> User:
        pass