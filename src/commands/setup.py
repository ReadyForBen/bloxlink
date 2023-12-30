import hikari
from resources.bloxlink import instance as bloxlink
from resources.binds import create_bind
from resources.roblox.groups import get_group
from resources.commands import CommandContext
from resources.response import Prompt, PromptPageData
from resources.components import Button, TextSelectMenu, TextInput
from resources.modals import build_modal
from resources.exceptions import RobloxNotFound
from resources.constants import BROWN_COLOR


class SetupPrompt(Prompt):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @Prompt.page(
        PromptPageData(
            title="Setup Bloxlink",
            description=("Thank you for choosing Bloxlink, the most popular Roblox-Discord integration! In a few simple prompts, we'll configure Bloxlink for your server."
                         ""
            ),
            components=[
                Button(
                    label="Next",
                    component_id="intro_next",
                    is_disabled=False,
                ),
                Button(
                    label="Cancel",
                    component_id="intro_cancel",
                    is_disabled=False,
                    style=Button.ButtonStyle.SECONDARY
                ),
            ]
        )
    )
    async def intro_page(self, interaction: hikari.CommandInteraction | hikari.ComponentInteraction, fired_component_id: str | None):
        match fired_component_id:
            case "intro_next":
                return await self.next()
            case "intro_cancel":
                return await self.finish()

    @Prompt.page(
        PromptPageData(
            title="Setup Bloxlink",
            description=("Should your members be given a different nickname? Please note that by default, Bloxlink will name users as: `Display Name (@Roblox Username)`.\n\n"
                         "You can select a preset template, or choose your own nickname format. You can even set a prefix (text before the nickname) and/or a suffix (text after the nickname)."
            ),
            components=[
                TextSelectMenu(
                    placeholder="Select a nickname preset...",
                    min_values=0,
                    max_values=1,
                    component_id="preset_nickname_select",
                    options=[
                        TextSelectMenu.Option(
                            label="Name users as: Roblox Display Name (@Roblox Username)",
                            value="{smart-name}",
                        ),
                        TextSelectMenu.Option(
                            label="Name users as: Roblox Username",
                            value="{roblox-name}",
                        ),
                        TextSelectMenu.Option(
                            label="Name users as: Roblox Display Name",
                            value="{display-name}",
                        ),
                        TextSelectMenu.Option(
                            label="Name users as: Discord Username",
                            value="{discord-name}",
                        ),
                        TextSelectMenu.Option(
                            label="Do not nickname users",
                            value="{disable-nicknaming}",
                        ),
                        TextSelectMenu.Option(
                            label="Choose my own nickname format...",
                            value="custom",
                        ),
                    ],
                ),
                Button(
                    label="Add a nickname prefix or suffix (optional)",
                    component_id="nickname_prefix_suffix",
                    is_disabled=False,
                ),
                Button(
                    label="Skip, leave unchanged",
                    component_id="nickname_skip",
                    is_disabled=False,
                    style=Button.ButtonStyle.SECONDARY
                ),
                Button(
                    label="Next",
                    component_id="nickname_submit",
                    is_disabled=True,
                    style=Button.ButtonStyle.SUCCESS
                )
            ],
        )
    )
    async def nickname_page(self, interaction: hikari.ComponentInteraction | hikari.ModalInteraction, fired_component_id: str):
        guild_nickname = (await bloxlink.fetch_guild_data(self.guild_id, "nicknameTemplate")).nicknameTemplate

        setup_nickname = await self.current_data(key_name="nicknameTemplate", raise_exception=False) or guild_nickname
        setup_nickname_prefix = await self.current_data(key_name="nicknameTemplate_prefix", raise_exception=False) or ""
        setup_nickname_suffix = await self.current_data(key_name="nicknameTemplate_suffix", raise_exception=False) or ""

        match fired_component_id:
            case "preset_nickname_select":
                select_nickname = (await self.current_data(key_name="preset_nickname_select")).get("values")[0]

                if select_nickname == "custom":
                    modal = build_modal(
                        title="Add a Custom Nickname",
                        command_name=self.command_name,
                        interaction=interaction,
                        prompt_data = {
                            "page_number": self.current_page_number,
                            "prompt_name": self.__class__.__name__,
                            "component_id": fired_component_id,
                            "prompt_message_id": self.custom_id.prompt_message_id
                        },
                        components=[
                            TextInput(
                                style=TextInput.TextInputStyle.SHORT,
                                placeholder="{smart-name}",
                                custom_id="nickname_prefix_input",
                                value="Type your nickname template...",
                                required=True
                            ),
                        ]
                    )

                    yield await self.response.send_modal(modal)

                    if not await modal.submitted():
                        return

                    setup_nickname = await modal.get_data("nickname_prefix_input")
                else:
                    setup_nickname = select_nickname

                await self.save_stateful_data(nicknameTemplate=setup_nickname)

                await self.edit_page(
                    components={
                        "nickname_submit": {
                            "is_disabled": False,
                        },
                    }
                )

                await self.response.send(
                    f"Updated the nickname template to `{setup_nickname_prefix}{setup_nickname}{setup_nickname_suffix}`!\n"
                    "You may also add a nickname prefix and/or suffix.\n"
                    "Press the **Next** button to continue to the next page.",
                    ephemeral=True
                )

            case "nickname_prefix_suffix":
                modal = build_modal(
                    title="Add a Nickname Prefix and/or Suffix",
                    command_name=self.command_name,
                    interaction=interaction,
                    prompt_data = {
                        "page_number": self.current_page_number,
                        "prompt_name": self.__class__.__name__,
                        "component_id": fired_component_id,
                        "prompt_message_id": self.custom_id.prompt_message_id
                    },
                    components=[
                        TextInput(
                            style=TextInput.TextInputStyle.SHORT,
                            placeholder="Type your nickname prefix...",
                            custom_id="nickname_prefix_input",
                            value="This will be shown FIRST in the nickname",
                            required=False
                        ),
                        TextInput(
                            style=TextInput.TextInputStyle.SHORT,
                            placeholder="Type your nickname suffix...",
                            custom_id="nickname_suffix_input",
                            value="This will be shown LAST in the nickname",
                            required=False
                        ),
                    ]
                )

                yield await self.response.send_modal(modal)

                if not await modal.submitted():
                    return

                modal_data = await modal.get_data()

                setup_nickname_prefix = modal_data.get("nickname_prefix_input") or ""
                setup_nickname_suffix = modal_data.get("nickname_suffix_input") or ""
                new_nickname_template = f"{setup_nickname_prefix}{setup_nickname}{setup_nickname_suffix}"

                await self.save_stateful_data(nicknameTemplate_prefix=setup_nickname_prefix, nicknameTemplate_suffix=setup_nickname_suffix)

                yield await self.response.send_first(
                    "Added the nickname prefix and/or suffix!\n\n"
                    f"Prefix: {setup_nickname_prefix}\n"
                    f"Suffix: {setup_nickname_suffix}\n"
                    f"New template: {new_nickname_template}",
                    ephemeral=True
                )

            case "nickname_skip" | "nickname_submit":
                yield await self.next()

    @Prompt.programmatic_page()
    async def verified_role_page(self, interaction: hikari.ComponentInteraction | hikari.ModalInteraction, fired_component_id: str):

        yield PromptPageData(
            title="Setup Bloxlink",
            description=(
                "Do you want to change the name of your **Verified role**? "
                "This is the role that Bloxlink will give to users when they verify.\n\n"
                # TODO: SHOW THE CURRENT NAME OF THE VERIFIED ROLE
            ),
            components=[
                Button(
                    label="Leave as default (Verified)",
                    component_id="verified_role_default",
                    is_disabled=False,
                ),
                Button(
                    label="Change the name",
                    component_id="verified_role_change_name",
                    is_disabled=False,
                ),
                Button(
                    label="Disable the Verified role",
                    component_id="verified_role_disable",
                    is_disabled=False,
                    style=Button.ButtonStyle.DANGER
                ),
                Button(
                    label="Next",
                    component_id="verified_role_submit",
                    is_disabled=True,
                    style=Button.ButtonStyle.SUCCESS
                )
            ],
        )

        match fired_component_id:
            case "verified_role_change_name":
                modal = build_modal(
                    title="Change Verified Role Name",
                    command_name=self.command_name,
                    interaction=interaction,
                    prompt_data = {
                        "page_number": self.current_page_number,
                        "prompt_name": self.__class__.__name__,
                        "component_id": fired_component_id,
                        "prompt_message_id": self.custom_id.prompt_message_id
                    },
                    components=[
                        TextInput(
                            style=TextInput.TextInputStyle.SHORT,
                            placeholder="Verified",
                            custom_id="verified_role_new_name",
                            value="Type your new verified role name...",
                            required=True
                        ),
                    ]
                )

                yield await self.response.send_modal(modal)

                if not await modal.submitted():
                    return

                new_verified_role_name = await modal.get_data("verified_role_new_name")

                await self.save_stateful_data(verifiedRoleName=new_verified_role_name)

                await self.edit_page(
                    components={
                        "verified_role_submit": {
                            "is_disabled": False,
                        },
                    }
                )

                await self.response.send(f"Updated the verified role name to `{new_verified_role_name}`!", ephemeral=True)

            case "verified_role_disable":
                await self.save_stateful_data(verifiedRoleName=None)

                yield await self.response.send_first(f"Disabled the verified role! Members will not get a Verified role when joining the server.", ephemeral=True)

                await self.next()

            case "verified_role_default" | "verified_role_submit":
                yield await self.next()

    @Prompt.page(
        PromptPageData(
            title="Setup Bloxlink",
            description=("Would you like to link a **Roblox group** to your server? This will create Discord roles that match "
                         "your Roblox group and assign it to server members.\n\n**Important:** if you require more advanced "
                         "group management, you can use the `/bind` command to link specific Roblox groups to specific Discord roles."
            ),
            components=[
                Button(
                    label="Link a group",
                    component_id="group_link",
                    is_disabled=False,
                ),
                Button(
                    label="Skip, leave unchanged",
                    component_id="group_skip",
                    is_disabled=False,
                    style=Button.ButtonStyle.SECONDARY
                ),
                Button(
                    label="Next",
                    component_id="group_submit",
                    is_disabled=True,
                    style=Button.ButtonStyle.SUCCESS
                )
            ],
        )
    )
    async def group_page(self, interaction: hikari.ComponentInteraction | hikari.ModalInteraction, fired_component_id: str):
        match fired_component_id:
            case "group_link":
                modal = build_modal(
                    title="Link a Group",
                    command_name=self.command_name,
                    interaction=interaction,
                    prompt_data = {
                        "page_number": self.current_page_number,
                        "prompt_name": self.__class__.__name__,
                        "component_id": fired_component_id,
                        "prompt_message_id": self.custom_id.prompt_message_id
                    },
                    components=[
                        TextInput(
                            style=TextInput.TextInputStyle.SHORT,
                            placeholder="https://www.roblox.com/groups/3587262/Bloxlink-Space#!/about",
                            custom_id="group_id_input",
                            value="Type your Group URL or ID",
                            required=True
                        ),
                    ]
                )

                yield await self.response.send_modal(modal)

                if not await modal.submitted():
                    return

                group_id = await modal.get_data("group_id_input")

                try:
                    group = await get_group(group_id)
                except RobloxNotFound:
                    yield await self.response.send_first("That group does not exist! Please try again.", ephemeral=True)
                    return

                await self.save_stateful_data(groupID=group.id)

                await self.edit_page(
                    components={
                        "group_submit": {
                            "is_disabled": False,
                        },
                    }
                )

                await self.response.send(
                    f"Linked the group **{group.name}** ({group.id})!\n"
                    "Press the **Next** button to continue to the next page.",
                    ephemeral=True
                )

            case "group_skip" | "group_submit":
                yield await self.next()

    @Prompt.programmatic_page()
    async def finish_setup(self, interaction: hikari.ComponentInteraction, fired_component_id: str | None):
        setup_data = await self.current_data()

        yield PromptPageData(
            title="Setup Bloxlink",
            description="You have reached the end of setup. Please confirm the following settings before finishing.",
            color=BROWN_COLOR,
            components=[
                Button(
                    label="Finish",
                    component_id="finish_setup",
                    is_disabled=False,
                    style=Button.ButtonStyle.SUCCESS
                ),
                Button(
                    label="Cancel",
                    component_id="cancel_setup",
                    is_disabled=False,
                    style=Button.ButtonStyle.SECONDARY
                )
            ],
        )


@bloxlink.command(
    category="Administration",
    defer_with_ephemeral=False,
    permissions=hikari.Permissions.MANAGE_GUILD,
    dm_enabled=False,
    prompts=[SetupPrompt],
)
class SetupCommand:
    """setup Bloxlink for your server"""

    async def __main__(self, ctx: CommandContext):
        return await ctx.response.send_prompt(SetupPrompt)
