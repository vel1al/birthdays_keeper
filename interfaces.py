from abc import ABCMeta, abstractmethod
from datetime import datetime
from structs import Birthday, User, GroupChat

class IDataTable:
    __metaclass__ = ABCMeta

    @classmethod
    @abstractmethod
    async def stable_changes(self) -> None:
        pass

    @classmethod
    @abstractmethod
    def b_is_user_in_table(self, user_id: str) -> bool:
        pass
    @classmethod
    @abstractmethod
    def b_is_chat_in_table(self, chat_id: str) -> bool:
        pass

    @classmethod
    @abstractmethod
    def get_user(self, user_id: str) -> User:
        pass

    @classmethod
    @abstractmethod
    def get_birthdays_by_id(self, birthday_id: str) -> Birthday:
        pass
    @classmethod
    @abstractmethod
    def get_birthday_by_date(self, date: datetime) -> dict[str, Birthday]:
        pass
    @classmethod
    @abstractmethod
    def get_birthday_owner(self, birthday_id: str) -> User:
        pass

    @classmethod
    @abstractmethod
    def get_chat_by_id(self, chat_id) -> GroupChat:
        pass
    @classmethod
    @abstractmethod
    def get_chat_id_by_user_id(self, user_id) -> str:
        pass

    @classmethod
    @abstractmethod
    def get_local(self, local, language) -> str:
        pass

    @classmethod
    @abstractmethod
    def add_new_user(self, user_id: str, user: User) -> None:
        pass
    @classmethod
    @abstractmethod
    def add_new_chat(self, chat_id, chat: GroupChat) -> None:
        pass
    @classmethod
    @abstractmethod
    def add_birthday(self, owner_id: str, birthday_id, birthday: Birthday) -> None:
        pass
    @classmethod
    @abstractmethod
    def remove_birthday(self, birthday_id: str) -> None:
        pass

    @classmethod
    @abstractmethod
    def adjust_birthday_field(self, birthday_id: str, field: str, value) -> None:
        pass
    @classmethod
    @abstractmethod
    def adjust_user_field(self, user_id: str, field: str, value) -> None:
        pass
    @classmethod
    @abstractmethod
    def rewrite_birthday(self, birthday_id: str, birthday: Birthday) -> None:
        pass
    @classmethod
    @abstractmethod
    def rewrite_user(self, user_id: str, user: User) -> None:
        pass