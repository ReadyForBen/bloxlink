from resources.bloxlink import instance as bloxlink
from resources.commands import CommandContext
from resources.response import Prompt, Response, PromptPageData
from resources.components import TextInput


@bloxlink.command(
    category="Miscellaneous",
    developer_only=True
)
class ModalTestCommand:
    """test modals"""

    async def __main__(self, ctx: CommandContext):
        modal = ctx.response.build_modal(
            title="Link a Group",
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

        await ctx.response.send_modal(modal)


        return await ctx.response.send_first("pong")
