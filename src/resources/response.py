import json
import uuid
from typing import Callable, Generic, Type, TypeVar

import hikari
from attrs import define, field, fields

import resources.components as Components
from resources.modals import Modal, ModalCustomID
from resources.bloxlink import instance as bloxlink

from .exceptions import AlreadyResponded, CancelCommand, PageNotFound


@define(slots=True)
class EmbedPrompt:
    """Represents a prompt consisting of an embed & components for the message."""

    embed: hikari.Embed = hikari.Embed()
    components: list = field(factory=list)
    page_number: int = 0


@define
class PromptCustomID:
    """Represents a custom ID for a prompt component."""

    command_name: str
    prompt_name: str
    user_id: int = field(converter=int)
    page_number: int = field(converter=int)
    component_custom_id: str

    def __str__(self):
        field_values = [str(getattr(self, field.name)) for field in fields(self.__class__)]
        return ":".join(field_values)

# @define
# class ModalCustomID:
#     """Represents a custom ID for a modal component."""

#     command_name: str
#     prompt_name: str
#     user_id: int = field(converter=int)
#     page_number: int = field(converter=int)
#     component_custom_id: str

#     def __str__(self):
#         field_values = [str(getattr(self, field.name)) for field in fields(self.__class__)]
#         return ":".join(field_values)


@define(slots=True)
class PromptPageData:
    description: str
    components: list[Components.Component] = field(default=list())
    title: str = None
    fields: list["Field"] = field(default=list())

    @define(slots=True)
    class Field:
        name: str
        value: str
        inline: bool = False


@define(slots=True)
class Page:
    func: Callable
    details: PromptPageData
    page_number: int
    programmatic: bool = False
    edited: bool = False


T = TypeVar("T", bound="PromptCustomID")


class Response:
    """Response to a discord interaction.

    Attributes:
        interaction (hikari.CommandInteraction): Interaction that this response is for.
        user_id (hikari.Snowflake): The user ID who triggered this interaction.
        responded (bool): Has this interaction been responded to. Default is False.
        deferred (bool): Is this response a deferred response. Default is False.
    """

    def __init__(self, interaction: hikari.CommandInteraction):
        self.interaction = interaction
        self.user_id = interaction.user.id
        self.responded = False
        self.deferred = False
        self.defer_through_rest = False

    async def defer(self, ephemeral: bool = False):
        """Defer this interaction. This needs to be yielded and called as the first response.

        Args:
            ephemeral (bool, optional): Should this message be ephemeral. Defaults to False.
        """

        if self.responded:
            # raise AlreadyResponded("Cannot defer a response that has already been responded to.")
            return

        self.responded = True
        self.deferred = True

        if self.defer_through_rest:
            if ephemeral:
                return await self.interaction.create_initial_response(
                    hikari.ResponseType.DEFERRED_MESSAGE_UPDATE, flags=hikari.messages.MessageFlag.EPHEMERAL
                )

            return await self.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)

        if self.interaction.type == hikari.InteractionType.APPLICATION_COMMAND:
            return self.interaction.build_deferred_response().set_flags(
                hikari.messages.MessageFlag.EPHEMERAL if ephemeral else None
            )

        return self.interaction.build_deferred_response(
            hikari.ResponseType.DEFERRED_MESSAGE_CREATE
        ).set_flags(hikari.messages.MessageFlag.EPHEMERAL if ephemeral else None)

    async def send_first(
        self,
        content: str = None,
        embed: hikari.Embed = None,
        components: list = None,
        ephemeral: bool = False,
        edit_original: bool = False,
    ):
        """Directly respond to Discord with this response. This should not be called more than once. This needs to be yielded."""

        """"
        Args:
            content (str, optional): Message content to send. Defaults to None.
            embed (hikari.Embed, optional): Embed to send. Defaults to None.
            components (list, optional): Components to attach to the message. Defaults to None.
            ephemeral (bool, optional): Should this message be ephemeral. Defaults to False.
        """

        print("responded=", self.responded)

        if self.responded:
            if edit_original:
                return await self.interaction.edit_initial_response(
                    content, embed=embed, components=components
                )

            return await self.send(content, embed=embed, components=components, ephemeral=ephemeral)

        self.responded = True

        match self.interaction:
            case hikari.CommandInteraction() | hikari.ModalInteraction():
                response_builder = self.interaction.build_response().set_flags(
                    hikari.messages.MessageFlag.EPHEMERAL if ephemeral else None
                )
            case hikari.ComponentInteraction():
                response_builder = self.interaction.build_response(
                    hikari.ResponseType.MESSAGE_CREATE
                    if not edit_original
                    else hikari.ResponseType.MESSAGE_UPDATE
                ).set_flags(hikari.messages.MessageFlag.EPHEMERAL if ephemeral else None)

            case _:
                raise NotImplementedError()

        if content:
            response_builder.set_content(content)
        # else:
        #     response_builder.clear_content()

        if embed:
            response_builder.add_embed(embed)
        # else:
        #     response_builder.clear_embeds()

        if components:
            for component in components:
                response_builder.add_component(component)
        else:
            response_builder.clear_components()

        # print(response_builder)

        return response_builder

    async def send(
        self,
        content: str = None,
        embed: hikari.Embed = None,
        components: list = None,
        ephemeral: bool = False,
        channel: hikari.GuildTextChannel = None,
        channel_id: str | int = None,
        **kwargs,
    ):
        """Send this Response to discord. This function only sends via REST and ignores the initial webhook response.

        Args:
            content (str, optional): Message content to send. Defaults to None.
            embed (hikari.Embed, optional): Embed to send. Defaults to None.
            components (list, optional): Components to attach to the message. Defaults to None.
            ephemeral (bool, optional): Should this message be ephemeral. Defaults to False.
            channel (hikari.GuildTextChannel, optional): Channel to send the message to. This will send as a regular message, not as an interaction response. Defaults to None.
            channel_id (int, str, optional): Channel ID to send the message to. This will send as a regular message, not as an interaction response. Defaults to None.
            **kwargs: match what hikari expects for interaction.execute() or interaction.create_initial_response()
        """

        if channel and channel_id:
            raise ValueError("Cannot specify both channel and channel_id.")

        if channel:
            return await channel.send(content, embed=embed, components=components, **kwargs)

        if channel_id:
            return await (await bloxlink.rest.fetch_channel(channel_id)).send(
                content, embed=embed, components=components, **kwargs
            )

        if ephemeral:
            kwargs["flags"] = hikari.messages.MessageFlag.EPHEMERAL

        if self.deferred:
            self.deferred = False
            self.responded = True

            kwargs.pop("flags", None)  # edit_initial_response doesn't support ephemeral

            return await self.interaction.edit_initial_response(
                content, embed=embed, components=components, **kwargs
            )

        if self.responded:
            return await self.interaction.execute(content, embed=embed, components=components, **kwargs)

        self.responded = True

        return await self.interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE, content, embed=embed, components=components, **kwargs
        )

    def send_modal(self, modal: Modal):
        """Send a modal response. This needs to be yielded."""

        # check if the modal was already submitted
        if isinstance(self.interaction, hikari.ModalInteraction):
            return

        return modal.builder

    # def build_modal(self, title: str, custom_id: str, components: list[Components.Component], *, command_name: str, prompt_data: dict = None):
    #     """Build a modal response. This needs to be separately returned."""

    #     # check if the modal was already submitted
    #     if isinstance(self.interaction, hikari.ModalInteraction):
    #         return

    #     new_custom_id = Components.get_custom_id(
    #         ModalCustomID,
    #         command_name=command_name,
    #         prompt_name=prompt_data["prompt_name"] or "",
    #         user_id=self.user_id,
    #         page_number=prompt_data["page_number"],
    #         component_custom_id=prompt_data["component_id"],
    #     )

    #     modal_builder = self.interaction.build_modal_response(title, str(new_custom_id))
    #     modal_action_row = hikari.impl.ModalActionRowBuilder()

    #     for component in components:
    #         modal_action_row.add_text_input(
    #             component.custom_id,
    #             component.value,
    #             placeholder=component.placeholder or "Enter a value...",
    #             min_length=component.min_length or 1,
    #             max_length=component.max_length or 2000,
    #             required=component.required or False,
    #             style=component.style or hikari.TextInputStyle.SHORT,
    #         )

    #     modal_builder.add_component(modal_action_row)

    #     return modal_builder

    async def prompt(self, prompt: Type["Prompt"], custom_id_data: dict = None):
        """Prompt the user with the first page of the prompt."""

        if self.interaction.type != hikari.InteractionType.APPLICATION_COMMAND:
            raise NotImplementedError("Can only call prompt() from a slash command.")

        new_prompt = prompt(self.interaction.command_name, self)
        new_prompt.insert_pages(prompt)

        if new_prompt.start_with_fresh_data:
            await new_prompt.clear_data()

        new_prompt.add_custom_id(0, "none", custom_id_data)

        hash_ = uuid.uuid4().hex
        print("prompt() hash=", hash_)
        return await new_prompt.run_page(custom_id_data, hash_=hash_, changing_page=True).__anext__()


class Prompt(Generic[T]):
    def __init__(
        self,
        command_name: str,
        response: Response,
        prompt_name: str,
        *,
        custom_id_format: Type[T] = PromptCustomID,
        start_with_fresh_data: bool = True,
    ):
        self.pages: list[Page] = []
        self.current_page_number = 0
        self.response = response
        self.command_name = command_name
        self.prompt_name = prompt_name
        self._custom_id_format: Type[T] = custom_id_format
        self.custom_id: T = None  # this is set in add_custom_id()
        self._pending_embed_changes = {}
        self.start_with_fresh_data = start_with_fresh_data

        response.defer_through_rest = True

    @staticmethod
    def page(page_details: PromptPageData):
        def wrapper(func: Callable):
            func.__page_details__ = page_details
            func.__programmatic_page__ = False
            func.__page__ = True
            return func

        return wrapper

    @staticmethod
    def programmatic_page():
        def wrapper(func: Callable):
            func.__page_details__ = None
            func.__programmatic_page__ = True
            func.__page__ = True
            return func

        return wrapper

    def add_custom_id(self, page_number: int, component_custom_id: str = "none", custom_id_data: dict = None):
        """Generate and save the custom ID."""

        self.custom_id: T = self._custom_id_format(
            command_name=self.command_name,
            prompt_name=self.__class__.__name__,
            page_number=page_number,
            component_custom_id=component_custom_id,
            user_id=self.response.user_id,
            **(custom_id_data or {}),
        )

    def build_page(
        self, command_name: str, user_id: int, page: Page, custom_id_data: dict = None, hash_=None
    ):
        """Build an EmbedPrompt from a prompt and page."""

        components = []
        embed = hikari.Embed(
            description=page.details.description,
            title=page.details.title or "Prompt",
        )

        if not self.custom_id:
            # this is only fired when response.prompt() is called
            self.add_custom_id(page.page_number, "none", custom_id_data)

        self.custom_id.page_number = page.page_number

        if page.details.components:
            button_action_row = bloxlink.rest.build_message_action_row()
            has_button = False

            for component in page.details.components:
                component_custom_id = Components.set_custom_id_field(
                    self._custom_id_format, str(self.custom_id), component_custom_id=component.component_id
                )
                print(hash_, "page components", component_custom_id, page.page_number, page.details.title)

                if component.type == Components.Component.ComponentType.BUTTON:
                    button_action_row.add_interactive_button(
                        component.style or hikari.ButtonStyle.PRIMARY,
                        component_custom_id,
                        label=component.label,
                        is_disabled=component.is_disabled,
                    )
                    has_button = True
                elif component.type == Components.Component.ComponentType.ROLE_SELECT_MENU:
                    role_action_row = bloxlink.rest.build_message_action_row()
                    role_action_row.add_select_menu(
                        hikari.ComponentType.ROLE_SELECT_MENU,
                        component_custom_id,
                        placeholder=component.placeholder,
                        min_values=component.min_values,
                        max_values=component.max_values,
                        is_disabled=component.is_disabled,
                    )
                    components.append(role_action_row)
                elif component.type == Components.Component.ComponentType.SELECT_MENU:
                    text_action_row = bloxlink.rest.build_message_action_row()
                    text_menu = text_action_row.add_text_menu(
                        component_custom_id,
                        placeholder=component.placeholder,
                        min_values=component.min_values,
                        max_values=component.max_values,
                        is_disabled=component.is_disabled,
                    )
                    for option in component.options:
                        text_menu.add_option(
                            option.name,
                            option.value,
                            description=option.description,
                            is_default=option.is_default,
                        )

                    components.append(text_action_row)

            if has_button:
                components.append(button_action_row)

        if page.details.fields:
            for field in page.details.fields:
                embed.add_field(field.name, field.value, inline=field.inline)

        if self._pending_embed_changes:
            if self._pending_embed_changes.get("description"):
                # page.details.description = self._pending_embed_changes["description"]
                embed.description = self._pending_embed_changes["description"]
                self._pending_embed_changes.pop("description")

            if self._pending_embed_changes.get("title"):
                # page.details.title = self._pending_embed_changes["title"]
                embed.title = self._pending_embed_changes["title"]
                self._pending_embed_changes.pop("title")

        return EmbedPrompt(
            embed=embed, components=components if components else None, page_number=page.page_number
        )

    def insert_pages(self, prompt: Type["Prompt"]):
        """Get all pages from the prompt.

        This needs to be called OUTSIDE of self to get the class attributes in insertion-order.

        """

        page_number = 0

        for (
            attr_name,
            attr,
        ) in prompt.__dict__.items():  # so we can get the class attributes in insertion-order
            if hasattr(attr, "__page__"):
                if getattr(attr, "__programmatic_page__", False):
                    self.pages.append(
                        Page(
                            func=getattr(self, attr_name),
                            programmatic=True,
                            details=PromptPageData(description="Unparsed programmatic page", components=[]),
                            page_number=page_number,
                        )
                    )
                else:
                    self.pages.append(
                        Page(
                            func=getattr(self, attr_name),
                            details=attr.__page_details__,
                            page_number=page_number,
                        )
                    )

                page_number += 1

    async def populate_programmatic_page(
        self, interaction: hikari.ComponentInteraction, fired_component_id: str | None = None
    ):
        current_page = self.pages[self.current_page_number]
        print("current_page=", current_page)

        if current_page.programmatic:
            generator_or_coroutine = current_page.func(interaction, fired_component_id)
            if hasattr(generator_or_coroutine, "__anext__"):
                async for generator_response in generator_or_coroutine:
                    if not generator_response:
                        continue

                    if isinstance(generator_response, PromptPageData):
                        page_details = generator_response
            else:
                page_details: PromptPageData = await generator_or_coroutine

            current_page.details = page_details

    async def entry_point(self, interaction: hikari.ComponentInteraction):
        """Entry point when a component is called. Redirect to the correct page."""

        self.custom_id = Components.parse_custom_id(self._custom_id_format, interaction.custom_id)
        self.current_page_number = self.custom_id.page_number
        self.current_page = self.pages[self.current_page_number]

        if interaction.user.id != self.custom_id.user_id:
            yield await self.response.send_first(
                f"This prompt can only be used by <@{self.custom_id.user_id}>.", ephemeral=True
            )
            return

        hash_ = uuid.uuid4().hex
        print("entry_point() hash=", hash_)

        async for generator_response in self.run_page(hash_=hash_):
            if isinstance(generator_response, hikari.Message):
                continue
            print(hash_, "generator_response entry_point()", generator_response)
            yield generator_response

    async def run_page(self, custom_id_data: dict = None, hash_=None, changing_page=False):
        """Run the current page."""

        hash_ = hash_ or uuid.uuid4().hex

        current_page = self.pages[self.current_page_number]

        print(hash_, "run_page() current page=", self.current_page_number, current_page.details.title)

        generator_or_coroutine = current_page.func(
            self.response.interaction, self.custom_id.component_custom_id if self.custom_id else None
        )

        # if this is a programmatic page, we need to run it first
        if current_page.programmatic:
            if hasattr(generator_or_coroutine, "__anext__"):
                async for generator_response in generator_or_coroutine:
                    if not generator_response:
                        continue

                    if isinstance(generator_response, PromptPageData):
                        page_details = generator_response
                    else:
                        yield generator_response
            else:
                page_details: PromptPageData = await generator_or_coroutine

            current_page.details = page_details
            built_page = self.build_page(
                self.command_name, self.response.user_id, current_page, custom_id_data, hash_
            )

            # this stops the page from being sent if the user has already moved on
            if current_page.page_number != self.current_page_number or current_page.edited:
                return

            # prompt() requires below send_first, but entry_point() doesn't since it calls other functions
            yield await self.response.send_first(
                embed=built_page.embed, components=built_page.components, edit_original=True
            )
            return

        print(
            hash_,
            "building page run_page(), current page=",
            self.current_page_number,
            current_page.details.title,
        )

        if changing_page:
            # we only build the page (embed) if we're changing pages

            built_page = self.build_page(
                self.command_name, self.response.user_id, current_page, custom_id_data, hash_
            )

            print(hash_, "run_page() built page", built_page.embed.title)

            if built_page.page_number != self.current_page_number:
                return

            yield await self.response.send_first(
                embed=built_page.embed, components=built_page.components, edit_original=True
            )

        if not current_page.programmatic:
            if hasattr(generator_or_coroutine, "__anext__"):
                async for generator_response in generator_or_coroutine:
                    if generator_response:
                        # if not changing_page and isinstance(generator_or_coroutine, PromptPageData):
                        #     continue

                        yield generator_response
            else:
                async_result = await generator_or_coroutine
                if async_result:
                    yield async_result

    async def current_data(self, raise_exception: bool = True):
        """Get the data for the current page from Redis."""

        redis_data = await bloxlink.redis.get(
            f"prompt_data:{self.command_name}:{self.prompt_name}:{self.response.interaction.user.id}"
        )

        if not redis_data:
            if raise_exception:
                raise CancelCommand("Previous data not found. Please restart this command.")

            return {}

        return json.loads(redis_data)

    async def _save_data_from_interaction(self, interaction: hikari.ComponentInteraction):
        """Save the data from the interaction from the current page to Redis."""

        custom_id = Components.parse_custom_id(PromptCustomID, interaction.custom_id)
        component_custom_id = custom_id.component_custom_id

        data = await self.current_data(raise_exception=False)
        data[component_custom_id] = Components.component_values_to_dict(interaction)

        await bloxlink.redis.set(
            f"prompt_data:{self.command_name}:{self.prompt_name}:{interaction.user.id}",
            json.dumps(data),
            ex=5 * 60,
        )

    async def save_stateful_data(self, **save_data):
        """Save the data for the current page to Redis."""

        data = await self.current_data(raise_exception=False) or {}
        data.update(save_data)

        await bloxlink.redis.set(
            f"prompt_data:{self.command_name}:{self.prompt_name}:{self.response.interaction.user.id}",
            json.dumps(data),
            ex=5 * 60,
        )

    async def clear_data(self, *remove_data_keys: list[str]):
        """Clear the data for the current page from Redis."""

        if remove_data_keys:
            data = await self.current_data(raise_exception=False) or {}

            for key in remove_data_keys:
                data.pop(key, None)

            await bloxlink.redis.set(
                f"prompt_data:{self.command_name}:{self.prompt_name}:{self.response.interaction.user.id}",
                json.dumps(data),
                ex=5 * 60,
            )
        else:
            await bloxlink.redis.delete(
                f"prompt_data:{self.command_name}:{self.prompt_name}:{self.response.interaction.user.id}"
            )

    async def previous(self, content: str = None):
        """Go to the previous page of the prompt."""

        self.current_page_number -= 1

        return await self.run_page(changing_page=True).__anext__()

    async def next(self, content: str = None):
        """Go to the next page of the prompt."""

        self.current_page_number += 1

        return await self.run_page(changing_page=True).__anext__()

    async def go_to(self, page: Callable, **kwargs):
        """Go to a specific page of the prompt."""

        for this_page in self.pages:
            if this_page.func == page:
                self.current_page_number = this_page.page_number
                break
        else:
            raise PageNotFound(f"Page {page} not found.")

        hash_ = uuid.uuid4().hex
        print("go_to() hash=", hash_)

        if kwargs:
            for attr_name, attr_value in kwargs.items():
                self._pending_embed_changes[attr_name] = attr_value

        return await self.run_page(hash_=hash_, changing_page=True).__anext__()

    async def finish(self, *, disable_components=True):
        """Finish the prompt."""

        current_page = self.pages[self.current_page_number]
        current_page.edited = True

        await self.clear_data()
        await self.ack()

        if disable_components and current_page.details.components:
            return await self.edit_page(
                components={
                    component.component_id: {"is_disabled": True}
                    for component in current_page.details.components
                }
            )

    async def ack(self):
        """Acknowledge the interaction. This tells the prompt to not send a response."""

        current_page = self.pages[self.current_page_number]
        current_page.edited = True

    async def edit_component(self, **component_data):
        """Edit a component on the current page."""

        hash_ = uuid.uuid4().hex
        print("edit_component() hash=", hash_)

        current_page = self.pages[self.current_page_number]

        if current_page.programmatic:
            await self.populate_programmatic_page(self.response.interaction)

        for component in current_page.details.components:
            for component_custom_id, kwargs in component_data.items():
                if component.component_id == component_custom_id:
                    for attr_name, attr_value in kwargs.items():
                        if attr_name == "component_id":
                            component.component_id = attr_value
                        else:
                            setattr(component, attr_name, attr_value)

        built_page = self.build_page(self.command_name, self.response.user_id, current_page, hash_=hash_)

        current_page.edited = True

        return await self.response.send_first(
            embed=built_page.embed, components=built_page.components, edit_original=True
        )

    async def edit_page(self, components=None, **new_page_data):
        """Edit the current page."""

        hash_ = uuid.uuid4().hex
        print("edit_page() hash=", hash_)

        current_page = self.pages[self.current_page_number]
        current_page.edited = True

        for attr_name, attr_value in new_page_data.items():
            self._pending_embed_changes[attr_name] = attr_value

        if components:
            for component_custom_id, kwargs in components.items():
                for component in current_page.details.components:
                    if component.component_id == component_custom_id:
                        for attr_name, attr_value in kwargs.items():
                            if attr_name == "component_id":
                                component.component_id = attr_value
                            else:
                                setattr(component, attr_name, attr_value)

        built_page = self.build_page(self.command_name, self.response.user_id, current_page, hash_=hash_)

        return await self.response.send_first(
            embed=built_page.embed, components=built_page.components, edit_original=True
        )
