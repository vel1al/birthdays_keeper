"get-beep-to-group-required": "awaiting for ",
"get-beep-to-chat-required": "beep to you?",
"get-congrats-required": "congrats from bot?",

async def collect_birthday_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    self._birthdays_blanks[str(update.effective_user.id)].name = update.effective_message.text
    await self.send_message_checked(update, context, message_local="add-birthday-get-date")

    return 1


async def collect_birthday_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date = datetime.date.fromisoformat(update.effective_message.text)
        self._birthdays_blanks[str(update.effective_user.id)].date = date

        await self.send_message_checked(update, context, message_local="add-birthday-get-beep-to-chat-required",
                                        reply_markup=ReplyKeyboardMarkup(
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

        elif self._birthdays_blanks[str(update.effective_user.id)].b_is_chat_event:
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

        await self.send_message_checked(update, context, message_local="add-birthday-get-congrats-required",
                                        markup=ReplyKeyboardMarkup(
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
                          "week": BeepInterval.week, "w": BeepInterval.week, "month": BeepInterval.month,
                          "m": BeepInterval.month}
        self._birthdays_blanks[str(update.effective_user.id)].beep_interval = beep_intervals[input_msg]
        if self._birthdays_blanks[str(update.effective_user.id)].b_is_chat_event:
            await self.send_message_checked(update, context, message_local="add-birthday-get-beep-to-group-required",
                                            markup=ReplyKeyboardMarkup(
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
        await self.send_message_checked(update, context,
                                        message_local="add-birthday-get-congrats-message-invalid-format")
        return 7

    else:
        self._birthdays_blanks[str(update.effective_user.id)].congrats_message = update.effective_message.text

        await self.ask_validate_birthday(update, context)
        return 8

    # CommandHandler('start', self.handle_start_command),
    # CommandHandler('reg_chat', self.handle_reg_chat_command),
    # ConversationHandler(
    #     entry_points=[CommandHandler('add_birthday', self.handle_add_birthday_command_initial)],
    #     states={
    #         0: [MessageHandler(filters=filters.ALL, callback=self.collect_b irthday_name)],
    #         1: [MessageHandler(filters=filters.ALL, callback=self.collect_birthday_date)],
    #         2: [MessageHandler(filters=filters.ALL, callback=self.collect_is_beep_required)],
    #         3: [MessageHandler(filters=filters.ALL, callback=self.collect_beep_interval)],
    #         4: [MessageHandler(filters=filters.ALL, callback=self.collect_is_beep_to_group_required)],
    #         5: [MessageHandler(filters=filters.ALL, callback=self.collect_is_congrats_required)],
    #         6: [MessageHandler(filters=filters.ALL, callback=self.collect_target_user_id)],
    #         7: [MessageHandler(filters=filters.ALL, callback=self.collect_congrats_message)],
    #         8: [MessageHandler(filters=filters.ALL, callback=self.validate_birthday)]
    #     }
    #     fallbacks=[CommandHandler('cancel', self.handle_add_birthday_cancel_command)]
    # ),
    # ConversationHandler(
    #     entry_points=[CommandHandler('adjust_birthday', self.handle_ajust_birthday_command)],
    # )
    # ,CommandHandler('help', self._handle_help_command)
    # ,CommandHandler('add', self._handle_add_command)