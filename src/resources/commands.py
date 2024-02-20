from __future__ import annotations

import json
import logging
import humanize
import re
from typing import Callable, Type, TypedDict, Unpack, Awaitable
from abc import ABC, abstractmethod
from datetime import timedelta
import hikari
from bloxlink_lib import BaseModelArbitraryTypes
from bloxlink_lib.database import redis
from resources.ui.components import parse_custom_id
from resources.constants import DEVELOPERS, BOT_RELEASE
from resources.exceptions import (
    BloxlinkForbidden, CancelCommand, PremiumRequired, UserNotVerified,
    RobloxNotFound, RobloxDown, Message, BindException
)
from resources.ui.modals import ModalCustomID
from resources.premium import get_premium_status
from resources.response import Prompt, PromptCustomID, PromptPageData, Response
from config import CONFIG

command_name_pattern = re.compile("(.+)Command")

slash_commands: dict[str, Command] = {}


class Command(BaseModelArbitraryTypes):
    """Base representation of a slash command on Discord"""

    name: str
    fn: Callable = None  # None if it has sub commands
    category: str = "Miscellaneous"
    permissions: hikari.Permissions = hikari.Permissions.NONE
    defer: bool = False
    defer_with_ephemeral: bool = False
    description: str = None
    options: list[hikari.CommandOption] = None
    subcommands: dict[str, Callable] = None
    rest_subcommands: list[hikari.CommandOption] = None
    accepted_custom_ids: dict[str, Callable] = None
    autocomplete_handlers: dict[str, Callable] = None
    dm_enabled: bool = False
    prompts: list[Type[Prompt]] = []
    developer_only: bool = False
    premium: bool = False
    pro_bypass: bool = False
    guild_ids: list[int] = [] # if empty, it's global
    cooldown: timedelta = None
    cooldown_key: str = "cooldown:{guild_id}:{user_id}:{command_name}"

    async def assert_premium(self, interaction: hikari.CommandInteraction):
        if self.premium or BOT_RELEASE == "PRO":
            premium_status = await get_premium_status(guild_id=interaction.guild_id, interaction=interaction)

            if not self.pro_bypass and ((BOT_RELEASE == "PRO" and premium_status.tier != "pro") or (self.premium and not premium_status.active)):
                raise PremiumRequired()

    async def assert_permissions(self, ctx: CommandContext):
        """Check if the user has the required permissions to run this command.

        Raises if the user does not have the required permissions.

        Args:
            ctx (CommandContext): Context for this command.

        Raises:
            BloxlinkForbidden: Raised if the user does not have the required permissions.
        """

        member = ctx.member

        if member.id in DEVELOPERS and BOT_RELEASE != "LOCAL":
            return True

        if (member.permissions & self.permissions) != self.permissions:
            missing_perms = ~member.permissions & self.permissions

            raise BloxlinkForbidden(
                f"You do not have the required permissions ({missing_perms}) to run this command.",
                ephemeral=True,
            )

        # second check seems redundant but it's to make it work locally because of the above bypass
        if self.developer_only and not member.id in DEVELOPERS:
            raise BloxlinkForbidden("This command is only available to developers.", ephemeral=True)

    async def assert_cooldown(self, ctx: CommandContext):
        """Check if the user can execute this command based on its cooldown."""

        user_id = ctx.user.id
        guild_id = ctx.guild_id
        command_name = self.name

        if not self.cooldown:
            return

        cooldown_key = self.cooldown_key.format(
            guild_id=guild_id,
            user_id=user_id,
            command_name=command_name,
        )

        seconds_left = await redis.ttl(cooldown_key)

        if seconds_left and seconds_left > 0:
            expiration_datetime = timedelta(seconds=seconds_left)
            expiration_str = humanize.naturaldelta(expiration_datetime)

            raise BloxlinkForbidden(f"You are on cooldown for this command. Please wait **{expiration_str}** before using it again.", ephemeral=True)

    async def set_cooldown(self, ctx: CommandContext):
        """Set the cooldown for the user."""

        if self.cooldown:
            user_id = ctx.user.id
            guild_id = ctx.guild_id
            command_name = self.name

            cooldown_key = self.cooldown_key.format(
                guild_id=guild_id,
                user_id=user_id,
                command_name=command_name,
            )

            await redis.set(cooldown_key, "1", expire=self.cooldown)

    async def execute(self, ctx: CommandContext, subcommand_name: str = None):
        """Execute a command (or its subcommand)

        Args:
            ctx (CommandContext): Context for this command.
            subcommand_name (str, optional): Name of the subcommand to trigger. Defaults to None.
        """

        await self.assert_permissions(ctx)
        await self.assert_cooldown(ctx)

        generator_or_coroutine = self.subcommands[subcommand_name](ctx) if subcommand_name else self.fn(ctx)

        if hasattr(generator_or_coroutine, "__anext__"):
            async for generator_response in generator_or_coroutine:
                yield generator_response

        else:
            yield await generator_or_coroutine

        # command executed without raising exceptions, so we can set the cooldown
        await self.set_cooldown(ctx)


class GenericCommand(ABC):
    """Generic command structure for slash commands."""

    @abstractmethod
    async def __main__(self, ctx: CommandContext) -> hikari.impl.InteractionMessageBuilder | None:
        """Main function to be executed when this command is triggered.

        This will be blank if the command has subcommands.

        Args:
            ctx (CommandContext): Context for this command.
        """

        raise NotImplementedError()


class NewCommandArgs(TypedDict, total=False):
    """Initialize a command with these arguments"""

    name: str
    category: str
    permissions: hikari.Permissions
    defer: bool
    defer_with_ephemeral: bool
    description: str
    options: list[hikari.commands.CommandOptions]
    subcommands: dict[str, Callable]
    rest_subcommands: list[hikari.CommandOption]
    accepted_custom_ids: dict[str, Awaitable]
    autocomplete_handlers: list[str]
    dm_enabled: bool
    prompts: list[Prompt]
    developer_only: bool
    premium: bool
    pro_bypass: bool
    guild_ids: list[int]
    cooldown: timedelta
    cooldown_key: str


class CommandContext(BaseModelArbitraryTypes):
    """Data related to a command that has been run.

    Attributes:
        command_name (str): The name of the command triggered.
        command_id (int): The ID of the command triggered.
        guild_id (int): The name of the command triggered.
        member (hikari.InteractionMember): The member that triggered this command.
        user (hikari.User): The user that triggered this command.
        resolved (hikari.ResolvedOptionData): Data of entities mentioned in command arguments that are
            resolved by Discord.
        options (dict): The options/arguments passed by the user to this command.
        interaction (hikari.CommandInteraction): The interaction object from Discord.
        response (Response): Bloxlink's wrapper for handling initial response sending.
    """

    command_name: str | None
    subcommand_name: str | None
    command_id: int | None
    guild_id: int
    member: hikari.InteractionMember
    user: hikari.User
    resolved: hikari.ResolvedOptionData | None
    options: dict[str, str | int] | None

    interaction: hikari.CommandInteraction | hikari.ModalInteraction | hikari.ComponentInteraction | hikari.AutocompleteInteraction

    response: Response


async def handle_interaction(interaction: hikari.Interaction):
    """
    One-stop shop for interaction (command, component, autocomplete) handling.
    Handles all errors from the handlers.

    Top level exceptions include default messages for custom exceptions that are defined in
    resources.exceptions.

    Caught exceptions currently consist of:
        - UserNotVerified
        - BloxlinkForbidden
        - hikari.errors.ForbiddenError
        - RobloxNotFound
        - RobloxDown
        - Message
        - Exception

    Args:
        interaction (hikari.Interaction): Interaction that was triggered.
    """

    correct_handler: Callable = None
    response = Response(interaction)

    match interaction:
        case hikari.CommandInteraction():
            correct_handler = handle_command
        case hikari.ComponentInteraction():
            correct_handler = handle_component
        case hikari.AutocompleteInteraction():
            correct_handler = handle_autocomplete
        case hikari.ModalInteraction():
            correct_handler = handle_modal
        case _:
            raise NotImplementedError()

    try:
        returned_already = False # we allow the command to keep executing but we will only return one response to Hikari

        async for command_response in correct_handler(interaction, response=response):
            if command_response:
                if not returned_already:
                    returned_already = True
                    yield command_response
                else:
                    logging.error(f"Interaction {interaction.type} attempted to send multiple responses! This is probably a bug.",
                                  exc_info=True,
                                  stack_info=True)

    except PremiumRequired:
        await response.send_premium_upsell(raise_exception=False)
    except UserNotVerified as message:
        await response.send(str(message) or "This user is not verified with Bloxlink!", ephemeral=message.ephemeral)
    except (BloxlinkForbidden, hikari.errors.ForbiddenError) as message:
        await response.send(
            str(message)
            or "I have encountered a permission error! Please make sure I have the appropriate permissions.",
            ephemeral=getattr(message, "ephemeral", False),
        )
    except RobloxNotFound as message:
        await response.send(
            str(message) or "This Roblox entity does not exist! Please check the ID and try again.",
            ephemeral=message.ephemeral,
        )
    except RobloxDown as message:
        await response.send(
            "Roblox appears to be down, so I was unable to process your command. "
            "Please try again in a few minutes.",
            ephemeral=message.ephemeral,
        )
    except (Message, BindException) as ex:
        await response.send(ex.message, ephemeral=ex.ephemeral)
    except CancelCommand:
        pass
    except Exception as ex: # pylint: disable=broad-except
        logging.exception(ex)
        await response.send(
            "An unexpected error occurred while processing this command. "
            "Please try again in a few minutes.",
            ephemeral=True,
        )


async def handle_command(
    interaction: hikari.CommandInteraction,
    response: Response,
    *,
    command_override: Command = None,
    command_options: dict = None,
    subcommand_name: str = None,
):
    """Handle a command interaction."""

    command = command_override
    command_options: dict = command_options or {}

    if not command_override:
        command_name = interaction.command_name
        command_type = interaction.command_type

        command = None
        subcommand_name: str = None

        # find command
        if command_type == hikari.CommandType.SLASH:
            command: Command = slash_commands.get(command_name)

            if not command:
                return

            # subcommand checking
            subcommand_option: list[hikari.CommandInteractionOption] = list(
                filter(lambda o: o.type == hikari.OptionType.SUB_COMMAND, interaction.options or [])
            )
            subcommand_name = subcommand_option[0].name if subcommand_option else None

        else:
            raise NotImplementedError()
    else:
        command_name = command_override.name

    await command.assert_premium(interaction)

    if not command_override:
        # get options
        if interaction.options:
            for option in interaction.options:
                if option.name == subcommand_name and option.options:
                    command_options = {o.name: o.value for o in option.options}
                    break
            else:
                command_options = {o.name: o.value for o in interaction.options}

        if command.defer:
            yield await response.defer(ephemeral=command.defer_with_ephemeral)

    ctx = build_context(
        interaction,
        response=response,
        command=command,
        options=command_options,
        subcommand_name=subcommand_name,
    )

    async for command_response in command.execute(ctx, subcommand_name=subcommand_name):
        if command_response:
            yield command_response


async def handle_autocomplete(interaction: hikari.AutocompleteInteraction, response: Response):
    """Handle an autocomplete interaction."""
    # Iterate through commands and find the autocomplete function that corresponds to the slash cmd option name.
    for command in slash_commands.values():
        if not command.autocomplete_handlers:
            continue

        if not command.name == interaction.command_name:
            continue

        for command_option in interaction.options:
            if not command_option.is_focused:
                continue

            autocomplete_fn = command.autocomplete_handlers.get(command_option.name)

            if not autocomplete_fn:
                logging.error(f'Command {command.name} has no auto-complete handler "{command_option.name}"!')
                return

            generator_or_coroutine = autocomplete_fn(build_context(interaction, response=response))

            if hasattr(generator_or_coroutine, "__anext__"):
                async for generator_response in generator_or_coroutine:
                    yield generator_response

            else:
                yield await generator_or_coroutine


async def handle_modal(interaction: hikari.ModalInteraction, response: Response):
    """Handle a modal interaction."""

    try:
        custom_id = interaction.custom_id
        components = [c for a in interaction.components for c in a.components]
        parsed_custom_id = parse_custom_id(ModalCustomID, custom_id)

        modal_data = {modal_component.custom_id: modal_component.value for modal_component in components}

        # save data from modal to redis
        await redis.set(f"modal_data:{custom_id}", modal_data, expire=timedelta(hours=1))

        # iterate through commands and find where
        # they called the modal from, and then execute the function again
        for command in slash_commands.values():
            if parsed_custom_id.type == "prompt":
                # cast it into a prompt custom id
                prompt_custom_id = parse_custom_id(PromptCustomID, custom_id)
                # find matching prompt handler
                for command_prompt in command.prompts:
                    if prompt_custom_id.prompt_name == command_prompt.__name__:
                        new_prompt = await command_prompt.new_prompt(
                            prompt_instance=command_prompt,
                            interaction=interaction,
                            response=response,
                            command_name=command.name,
                        )

                        async for generator_response in new_prompt.entry_point(interaction):
                            if not isinstance(generator_response, PromptPageData):
                                logging.debug("2 %s", generator_response)
                                yield generator_response

                        break

            elif parsed_custom_id.type == "command":
                # find matching command handler
                if command.name == parsed_custom_id.command_name and (
                    parsed_custom_id.subcommand_name
                    and parsed_custom_id.subcommand_name in command.subcommands
                    or not parsed_custom_id.subcommand_name
                ):
                    command_options_data = await redis.get(f"modal_command_options:{custom_id}")
                    command_options = json.loads(command_options_data) if command_options_data else {}

                    generator_or_coroutine = handle_command(
                        interaction,
                        response,
                        command_override=command,
                        command_options=command_options,
                        subcommand_name=parsed_custom_id.subcommand_name,
                    )

                    if hasattr(generator_or_coroutine, "__anext__"):
                        async for generator_response in generator_or_coroutine:
                            yield generator_response
                    else:
                        yield await generator_or_coroutine

                    break

    finally:
        # clear modal data from redis so it doesn't get reused if they execute the command again
        await redis.delete(f"modal_data:{custom_id}")


async def handle_component(interaction: hikari.ComponentInteraction, response: Response):
    """Handle a component interaction."""

    custom_id = interaction.custom_id

    # iterate through commands and find the custom_id mapped function
    for command in slash_commands.values():
        # find matching custom_id handler
        if command.accepted_custom_ids:
            for accepted_custom_id, custom_id_fn in command.accepted_custom_ids.items():
                if custom_id.startswith(accepted_custom_id):
                    generator_or_coroutine = custom_id_fn(build_context(interaction, response=response))

                    if hasattr(generator_or_coroutine, "__anext__"):
                        async for generator_response in generator_or_coroutine:
                            yield generator_response

                    else:
                        yield await generator_or_coroutine

                    return

        # find matching prompt handler
        if command.prompts:
            for command_prompt in command.prompts:
                try:
                    parsed_custom_id = parse_custom_id(PromptCustomID, custom_id)
                except (TypeError, IndexError):
                    # Keeps prompts from preventing normal components from firing on iteration.
                    # Since we check for a valid handler
                    continue

                if (
                    parsed_custom_id.command_name == command.name
                    and parsed_custom_id.prompt_name in (command_prompt.override_prompt_name, command_prompt.__name__)
                ):
                    new_prompt = await command_prompt.new_prompt(
                        prompt_instance=command_prompt,
                        interaction=interaction,
                        response=response,
                        command_name=command.name,
                    )

                    async for generator_response in new_prompt.entry_point(interaction):
                        if not isinstance(generator_response, PromptPageData):
                            logging.debug("3 %s", generator_response)
                            yield generator_response

                    return


def new_command(command: Callable, **command_args: Unpack[NewCommandArgs]):
    """Registers a command with Bloxlink.

    This is only used for the wrapper function in resources.bloxlink on the bot object. Commands should not
    be added using this method directly.

    Args:
        command (Callable): The command to register locally.
    """
    new_command_class = command()

    command_name = command_args.get("name") or command_name_pattern.search(command.__name__).group(1).lower()
    command_fn = getattr(new_command_class, "__main__", None)  # None if it has sub commands
    subcommands: dict[str, Callable] = {}
    rest_subcommands: list[hikari.CommandOption] = []

    command_args["description"] = new_command_class.__doc__

    for attr_name in dir(new_command_class):
        attr = getattr(new_command_class, attr_name)

        if hasattr(attr, "__issubcommand__"):
            rest_subcommands.append(
                hikari.CommandOption(
                    type=hikari.OptionType.SUB_COMMAND,
                    name=attr.__name__,
                    description=attr.__doc__,
                    options=attr.__subcommandattrs__.get("options"),
                )
            )
            subcommands[attr_name] = attr

    slash_commands[command_name] = Command(
        fn=command_fn,
        name=command_name,
        rest_subcommands=rest_subcommands,
        subcommands=subcommands,
        **command_args,
    )

    for alias in command_args.get("aliases", []):
        slash_commands[alias] = Command(
            fn=command_fn,
            name=alias,
            **command_args,
        )

        logging.info(f"Registered command alias {alias} of {command_name}")

    logging.info(f"Registered command {command_name}")


async def sync_commands(bot: hikari.RESTBot):
    """Publish our slash commands to Discord.

    Args:
        bot (hikari.RESTBot): The bot object to publish slash commands for.
    """

    commands: list[hikari.PartialCommand] = []
    guild_commands: dict[int, list[hikari.PartialCommand]] = {}

    for new_command_data in slash_commands.values():
        command: hikari.api.SlashCommandBuilder = bot.rest.slash_command_builder(
            new_command_data.name, new_command_data.description
        )

        if new_command_data.rest_subcommands:
            for sucommand in new_command_data.rest_subcommands:
                command.add_option(sucommand)

        if new_command_data.permissions:
            command.set_default_member_permissions(new_command_data.permissions)

        if new_command_data.options:
            for option in new_command_data.options:
                command.add_option(option)

        if new_command_data.dm_enabled is not None:
            command.set_is_dm_enabled(new_command_data.dm_enabled)

        if not new_command_data.guild_ids:
            commands.append(command)
        else:
            for guild_id in new_command_data.guild_ids:
                guild_commands[guild_id] = guild_commands.get(guild_id, [])
                guild_commands[guild_id].append(command)

    await bot.rest.set_application_commands(
        application=CONFIG.DISCORD_APPLICATION_ID,
        commands=commands,
    )

    if guild_commands:
        for guild_id, commands in guild_commands.items():
            await bot.rest.set_application_commands(
                application=CONFIG.DISCORD_APPLICATION_ID,
                commands=commands,
                guild=guild_id
            )


    logging.info(f"Registered {len(slash_commands)} slash commands.")

    if guild_commands:
        logging.info(f"Registered commands for {len(guild_commands)} guilds.")


def build_context(
    interaction: hikari.CommandInteraction | hikari.ComponentInteraction | hikari.AutocompleteInteraction,
    subcommand_name: str = None,
    response: Response = None,
    command: Command = None,
    options = None,
) -> CommandContext:
    """Build a CommandContext from an interaction.

    Args:
        interaction (hikari.CommandInteraction | hikari.ComponentInteraction | hikari.AutocompleteInteraction): The interaction to build a context for.
        response (Response, optional): The response object for this interaction. Defaults to None. It will be created if not provided.
        command (Command, optional): The command that this interaction is for. Defaults to None. This is only useful for handlers to know the current command name.
        options (dict, optional): The options/arguments passed by the user to this command. Defaults to None. This is only useful to provide for subcommands.
    Returns:
        CommandContext: The built context.
    """

    return CommandContext(
        command_name=(command and command.name) or getattr(interaction, "command_name", None),
        subcommand_name=subcommand_name,
        command_id=interaction.command_id if hasattr(interaction, "command_id") else None,
        guild_id=interaction.guild_id,
        member=interaction.member,
        user=interaction.user,
        resolved=interaction.resolved if hasattr(interaction, "resolved") else None,
        options=(
            options or {o.name: o.value for o in interaction.options}
            if getattr(interaction, "options", None)
            else None
        ),
        interaction=interaction,
        response=response or Response(interaction),
    )
