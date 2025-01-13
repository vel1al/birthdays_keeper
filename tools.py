from telegram.constants import ChatType
from telegram.ext._contexttypes import ContextTypes
from telegram.ext import CallbackContext
from telegram import InlineKeyboardButton, Update
from collections.abc import Awaitable, Callable


def validate_input(valid_input: list[str], callback_index: str = "", invalid_response_int: int = -1, invalid_response: Callable[Update, CallbackContext, str, Awaitable[None]] = None):
    def inner_decorator(func: Callable[..., Awaitable[int]]):
        async def wrapped(*args, **kwargs) -> int:
            update: Update = kwargs.get('update')
            context: ContextTypes.DEFAULT_TYPE = kwargs.get('context')
            if update is None:
                for arg in args:
                    if isinstance(arg, Update):
                        update = arg
                    elif isinstance(arg, CallbackContext):
                        context = arg

            if update is not None:
                input_msg = None
                if update.message is not None:
                    input_msg = update.message.text
                elif update.callback_query is not None:
                    input_msg = update.callback_query.data.replace(callback_index, "")

                if input_msg is not None and input_msg in valid_input:
                    kwargs['checked_input'] = input_msg
                    return await func(*args, **kwargs)

                if invalid_response is not None and context is not None:
                    await invalid_response(update, context, input_msg)
            return invalid_response_int
        return wrapped
    return inner_decorator

def dict_to_inline_keyboard(buttons: [[dict[str, str]]]) -> [[InlineKeyboardButton]]:
    output = [[]]
    for button_line in buttons:
        keyboard_line = []
        for button_dict in button_line:
            text, callback = button_dict['text'], button_dict['callback']
            keyboard_line.append(InlineKeyboardButton(text=text, callback_data=callback))
        output.append(keyboard_line)

    return output

def b_is_valid_group_chat(chat_type: str) -> bool:
    return not (chat_type == ChatType.CHANNEL or chat_type == ChatType.PRIVATE)

def get_cutoff(list_len: int, page_size: int, page: int) -> int:
    begin_chat, cutoff = (page - 1) * page_size - 1, page_size
    if list_len < page_size:
        cutoff = list_len
    else:
        diff = list_len - page * page_size
        if diff < 0 and abs(diff) > page_size:
            return 0
        if diff < 0 and abs(diff) < page_size:
            cutoff = diff

    return cutoff