import os
import re
import json
import asyncio
from copy import deepcopy

import discord
from discord.ext import commands
from dotenv import load_dotenv

from oc_layout import (
    CustomLayoutButton,
    PreviewLayoutButton,
    render_oc_layout,
    layout_is_enabled,
)

from oc_json import setup_oc_json_commands

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!"
DATA_FILE = "oc_data.json"

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN was not found. Create a .env file and add:\n"
        "DISCORD_TOKEN=your_bot_token_here"
    )

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
)

TRIGGER_VOICE_CHANNEL_ID = None
data_lock = asyncio.Lock()

def default_book():
    return {
        "profile": {
            "name": "",
            "pronouns": "",
            "about": "",
            "status": "",
            "links": "",
            "image": "",
            "banner": "",
            "color": "#5865F2",
        },
        "world": {
            "name": "",
            "genre": "",
            "setting": "",
            "lore": "",
            "rules": "",
            "notes": "",
            "image": "",
            "banner": "",
            "color": "#2B8C85",
        },
        "ocs": {},
        "proxies": {},
    }

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        if isinstance(loaded, dict):
            return loaded

    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not load {DATA_FILE}: {error}")

    return {}

oc_books = load_data()

async def save_data():
    async with data_lock:
        temp_file = f"{DATA_FILE}.tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(oc_books, file, indent=4, ensure_ascii=False)

        os.replace(temp_file, DATA_FILE)

def get_book(user_id):
    key = str(user_id)

    if key not in oc_books:
        oc_books[key] = default_book()

    book = oc_books[key]
    defaults = default_book()

    for section, values in defaults.items():
        if section not in book or not isinstance(book[section], dict):
            book[section] = deepcopy(values)

        if isinstance(values, dict):
            for field, default_value in values.items():
                book[section].setdefault(field, default_value)

    book.setdefault("proxies", {})
    if not isinstance(book["proxies"], dict):
        book["proxies"] = {}

    for oc in book["ocs"].values():
        if isinstance(oc, dict):
            oc.setdefault("banner", "")
            oc.setdefault("color", "#5865F2")
            oc.setdefault("image", "")

    return book

def normalize_name(name):
    return re.sub(r"\s+", " ", name.strip()).lower()

def valid_url(url):
    return bool(re.match(r"^https?://", str(url or "").strip(), re.IGNORECASE))

def normalize_hex(value, fallback="#5865F2"):
    value = str(value or "").strip()

    if not value:
        return fallback

    value = value.lstrip("#")

    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return f"#{value.upper()}"

    return None

def embed_color(value, fallback=discord.Color.blurple()):
    normalized = normalize_hex(value)

    if normalized is None:
        return fallback

    return discord.Color(int(normalized[1:], 16))

def image_hint(url):
    if not url:
        return ""

    return (
        "Images must be direct/public HTTPS image URLs. "
        "On Tumblr/Pinterest/etc., use **Copy Image Address** when possible; "
        "a normal post/pin page URL may not render as an image in Discord."
    )

def clip(text, limit=1024, fallback="Not set."):
    text = str(text or "").strip()

    if not text:
        return fallback

    if len(text) <= limit:
        return text

    return text[: limit - 3] + "..."

def make_embed(title, description="", color=discord.Color.blurple()):
    return discord.Embed(
        title=title,
        description=description,
        color=color,
    )

def build_book_embed(member):
    book = get_book(member.id)
    profile = book["profile"]
    world = book["world"]
    ocs = book["ocs"]

    display_name = profile["name"] or member.display_name

    description = profile["about"] or (
        f"Welcome to **{display_name}'s OC Book**.\n"
        "This page contains their character collection and world information."
    )

    embed = make_embed(
        f" {display_name}'s OC Book",
        description,
        embed_color(profile.get("color"), discord.Color.blurple()),
    )

    embed.set_author(
        name=member.display_name,
        icon_url=member.display_avatar.url,
    )

    if profile["pronouns"]:
        embed.add_field(
            name="Pronouns",
            value=clip(profile["pronouns"]),
            inline=True,
        )

    if profile["status"]:
        embed.add_field(
            name="Status",
            value=clip(profile["status"]),
            inline=True,
        )

    embed.add_field(
        name=" Characters",
        value=f"**{len(ocs)}** OC(s)",
        inline=True,
    )

    if profile["links"]:
        embed.add_field(
            name="[LINK] Links",
            value=clip(profile["links"]),
            inline=False,
        )

    if world["name"] or world["genre"] or world["setting"]:
        world_summary = []

        if world["name"]:
            world_summary.append(f"**World:** {world['name']}")

        if world["genre"]:
            world_summary.append(f"**Genre:** {world['genre']}")

        if world["setting"]:
            world_summary.append(f"**Setting:** {world['setting']}")

        embed.add_field(
            name="[WORLD] World",
            value="\n".join(world_summary),
            inline=False,
        )

    embed.set_footer(
        text="Use the buttons below to explore the OC collection."
    )

    if valid_url(profile.get("image")):
        embed.set_thumbnail(url=profile["image"])

    if valid_url(profile.get("banner")):
        embed.set_image(url=profile["banner"])

    return embed

def build_oc_list_embed(member):
    book = get_book(member.id)
    ocs = book["ocs"]

    embed = make_embed(
        f" {member.display_name}'s Characters",
        "Select a character below to view their full profile.",
        discord.Color.purple(),
    )

    if not ocs:
        embed.description = (
            "This OC Book doesn't have any characters yet."
        )
        return embed

    names = [
        oc_data.get("name", key)
        for key, oc_data in ocs.items()
    ]

    lines = [
        f"**{index}.** {name}"
        for index, name in enumerate(names, start=1)
    ]

    embed.description = "\n".join(lines)
    embed.set_footer(
        text=f"{len(names)} character(s) - Choose one from the menu below."
    )

    return embed

def build_world_embed(member):
    world = get_book(member.id)["world"]

    embed = make_embed(
        f"[WORLD] {member.display_name}'s Innerworld",
        world["name"] or "No world name has been set.",
        embed_color(world.get("color"), discord.Color.dark_teal()),
    )

    if world["genre"]:
        embed.add_field(
            name="? Genre",
            value=clip(world["genre"]),
            inline=False,
        )

    if world["setting"]:
        embed.add_field(
            name="? Setting",
            value=clip(world["setting"]),
            inline=False,
        )

    if world["lore"]:
        embed.add_field(
            name=" Lore",
            value=clip(world["lore"]),
            inline=False,
        )

    if world["rules"]:
        embed.add_field(
            name="? Rules / World Rules",
            value=clip(world["rules"]),
            inline=False,
        )

    if world["notes"]:
        embed.add_field(
            name="Notes",
            value=clip(world["notes"]),
            inline=False,
        )

    if valid_url(world.get("image")):
        embed.set_thumbnail(url=world["image"])

    if valid_url(world.get("banner")):
        embed.set_image(url=world["banner"])

    if not any(world.get(key) for key in [
        "name", "genre", "setting", "lore", "rules", "notes"
    ]):
        embed.description = (
            "No innerworld settings have been added yet."
        )

    return embed

def build_oc_embed(owner, oc):
    embed = make_embed(
        f" {oc['name']}",
        oc["personality"] or "No personality information has been added.",
        embed_color(oc.get("color"), discord.Color.blue()),
    )

    embed.set_author(
        name=f"Owned by {owner.display_name}",
        icon_url=owner.display_avatar.url,
    )

    if oc["age"]:
        embed.add_field(
            name="? Age",
            value=clip(oc["age"]),
            inline=True,
        )

    if oc["pronouns"]:
        embed.add_field(
            name="? Pronouns",
            value=clip(oc["pronouns"]),
            inline=True,
        )

    if oc["appearance"]:
        embed.add_field(
            name="[PROFILE] Appearance",
            value=clip(oc["appearance"]),
            inline=False,
        )

    if oc["lore"]:
        embed.add_field(
            name=" Lore / Backstory",
            value=clip(oc["lore"]),
            inline=False,
        )

    if oc["likes"]:
        embed.add_field(
            name="? Likes",
            value=clip(oc["likes"]),
            inline=True,
        )

    if oc["dislikes"]:
        embed.add_field(
            name="? Dislikes",
            value=clip(oc["dislikes"]),
            inline=True,
        )

    if oc["abilities"]:
        embed.add_field(
            name="? Abilities",
            value=clip(oc["abilities"]),
            inline=False,
        )

    if oc["relationships"]:
        embed.add_field(
            name="? Relationships",
            value=clip(oc["relationships"]),
            inline=False,
        )

    if oc["notes"]:
        embed.add_field(
            name="Notes",
            value=clip(oc["notes"]),
            inline=False,
        )

    if valid_url(oc.get("image")):
        embed.set_thumbnail(url=oc["image"])

    if valid_url(oc.get("banner")):
        embed.set_image(url=oc["banner"])

    return embed

class OCBookView(discord.ui.View):

    def __init__(self, owner, viewer_id, timeout=600):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.viewer_id = viewer_id

    async def interaction_check(self, interaction):
        return True

    async def deny_owner_edit(self, interaction):
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message(
                " Only the owner of this OC Book can edit it.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="View OCs",
        style=discord.ButtonStyle.primary,
    )
    async def view_ocs(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_oc_list_embed(self.owner),
            view=OCListView(
                self.owner,
                interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="World Settings",
        style=discord.ButtonStyle.secondary,
    )
    async def world(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_world_embed(self.owner),
            view=OCWorldView(
                self.owner,
                interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="Edit Book",
        style=discord.ButtonStyle.success,
    )
    async def edit_book(self, interaction, button):
        if not await self.deny_owner_edit(interaction):
            return

        await interaction.response.send_modal(
            ProfileModal(self.owner)
        )

    @discord.ui.button(
        label="Appearance",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def appearance(self, interaction, button):
        if not await self.deny_owner_edit(interaction):
            return

        await interaction.response.send_modal(
            ProfileAppearanceModal(self.owner)
        )

class OCListView(discord.ui.View):

    def __init__(self, owner, viewer_id, timeout=600):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.viewer_id = viewer_id

        book = get_book(owner.id)
        ocs = book["ocs"]

        if ocs:
            options = []

            for key, oc in list(ocs.items())[:25]:
                options.append(
                    discord.SelectOption(
                        label=oc["name"][:100],
                        value=key,
                        description=(
                            clip(
                                oc["personality"],
                                100,
                                "View this character's profile.",
                            )
                        ),
                    )
                )

            self.add_item(OCSelect(options))

        if viewer_id == owner.id:
            self.add_item(AddOCButton())

    @discord.ui.button(
        label="Back",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_book_embed(self.owner),
            view=OCBookView(
                self.owner,
                interaction.user.id,
            ),
        )

async def custom_oc_render(owner, oc):
    try:
        image = await render_oc_layout(oc, owner=str(owner.display_name))
        file = discord.File(image, filename="oc-custom-layout.png")
        embed = make_embed(
            f" {oc['name']}", "Custom OC layout",
            embed_color(oc.get("color"), discord.Color.blue())
        )
        embed.set_image(url="attachment://oc-custom-layout.png")
        embed.set_footer(text=f"Owned by {owner.display_name} - Custom Layout")
        return embed, file
    except Exception as e:
        print(f"Custom OC layout failed: {e}")
        return None, None

class OCSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Choose an OC to view...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction):
        view = self.view

        book = get_book(view.owner.id)
        oc = book["ocs"].get(self.values[0])

        if oc is None:
            await interaction.response.send_message(
                " That OC no longer exists.",
                ephemeral=True,
            )
            return

        oc_key = self.values[0]
        profile_view = OCProfileView(view.owner, interaction.user.id, oc_key)
        if layout_is_enabled(oc):
            embed, file = await custom_oc_render(view.owner, oc)
            if embed:
                await interaction.response.edit_message(
                    embed=embed, attachments=[file], view=profile_view
                )
                return
        await interaction.response.edit_message(
            embed=build_oc_embed(view.owner, oc), attachments=[], view=profile_view
        )

class AddOCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Add OC",
            style=discord.ButtonStyle.success,
            row=3,
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(
            OCModal(interaction.user)
        )

class OCProfileView(discord.ui.View):

    def __init__(self, owner, viewer_id, oc_key, timeout=600):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.viewer_id = viewer_id
        self.oc_key = oc_key

        if viewer_id == owner.id:
            self.add_item(EditOCButton())
            self.add_item(EditOCAppearanceButton())
            get_oc = lambda uid, key: get_book(uid)["ocs"].get(key)
            self.add_item(CustomLayoutButton(owner.id, oc_key, get_oc, save_data))
            self.add_item(PreviewLayoutButton(owner.id, oc_key, get_oc))

    @discord.ui.button(
        label="Back to OCs",
        style=discord.ButtonStyle.secondary,
    )
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_oc_list_embed(self.owner),
            view=OCListView(
                self.owner,
                interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="World",
        style=discord.ButtonStyle.secondary,
    )
    async def world(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_world_embed(self.owner),
            view=OCWorldView(
                self.owner,
                interaction.user.id,
            ),
        )

class EditOCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Edit OC",
            style=discord.ButtonStyle.success,
            row=2,
        )

    async def callback(self, interaction):
        view = self.view
        book = get_book(view.owner.id)
        oc = book["ocs"].get(view.oc_key)

        if oc is None:
            await interaction.response.send_message(
                " That OC no longer exists.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            OCModal(
                interaction.user,
                existing_key=view.oc_key,
                existing_oc=oc,
            )
        )

class EditOCAppearanceButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Appearance",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

    async def callback(self, interaction):
        view = self.view

        if interaction.user.id != view.owner.id:
            await interaction.response.send_message(
                " Only the OC owner can edit its appearance.",
                ephemeral=True,
            )
            return

        oc = get_book(view.owner.id)["ocs"].get(view.oc_key)

        if oc is None:
            await interaction.response.send_message(
                " That OC no longer exists.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            OCAppearanceModal(
                view.owner,
                view.oc_key,
                oc,
            )
        )

class OCWorldView(discord.ui.View):

    def __init__(self, owner, viewer_id, timeout=600):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.viewer_id = viewer_id

        if viewer_id == owner.id:
            self.add_item(EditWorldButton())
            self.add_item(EditWorldAppearanceButton())

    @discord.ui.button(
        label="Back to Book",
        style=discord.ButtonStyle.secondary,
    )
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=build_book_embed(self.owner),
            view=OCBookView(
                self.owner,
                interaction.user.id,
            ),
        )

class EditWorldButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Edit World",
            style=discord.ButtonStyle.success,
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(
            WorldModal(interaction.user)
        )

class EditWorldAppearanceButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Appearance",
            style=discord.ButtonStyle.secondary,
        )

    async def callback(self, interaction):
        view = self.view

        if interaction.user.id != view.owner.id:
            await interaction.response.send_message(
                " Only the owner can edit the innerworld appearance.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            WorldAppearanceModal(view.owner)
        )

class ProfileModal(discord.ui.Modal, title="Edit OC Book"):
    display_name = discord.ui.TextInput(
        label="Display Name",
        placeholder="What should your OC Book be called?",
        max_length=100,
        required=False,
    )

    pronouns = discord.ui.TextInput(
        label="Pronouns",
        placeholder="e.g. they/them",
        max_length=100,
        required=False,
    )

    about = discord.ui.TextInput(
        label="About",
        placeholder="Tell people about yourself / your collection...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    status = discord.ui.TextInput(
        label="Status",
        placeholder="e.g. Open to interaction / Do Not Interact",
        max_length=200,
        required=False,
    )

    links = discord.ui.TextInput(
        label="Links",
        placeholder="Socials, Carrd, website, etc.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

        profile = get_book(owner.id)["profile"]

        self.display_name.default = profile["name"]
        self.pronouns.default = profile["pronouns"]
        self.about.default = profile["about"]
        self.status.default = profile["status"]
        self.links.default = profile["links"]

    async def on_submit(self, interaction):
        profile = get_book(self.owner.id)["profile"]

        profile["name"] = str(self.display_name.value).strip()
        profile["pronouns"] = str(self.pronouns.value).strip()
        profile["about"] = str(self.about.value).strip()
        profile["status"] = str(self.status.value).strip()
        profile["links"] = str(self.links.value).strip()

        await save_data()

        await interaction.response.send_message(
            " Your OC Book information has been updated.",
            ephemeral=True,
        )

class ProfileAppearanceModal(discord.ui.Modal, title=" Book Appearance"):
    color = discord.ui.TextInput(
        label="Book Color",
        placeholder="Hex color, e.g. #8B5CF6",
        max_length=7,
        required=False,
    )

    pfp = discord.ui.TextInput(
        label="Profile Picture URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    banner = discord.ui.TextInput(
        label="Banner URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

        profile = get_book(owner.id)["profile"]
        self.color.default = profile.get("color", "#5865F2")
        self.pfp.default = profile.get("image", "")
        self.banner.default = profile.get("banner", "")

    async def on_submit(self, interaction):
        profile = get_book(self.owner.id)["profile"]

        new_color = normalize_hex(self.color.value, "#5865F2")

        if new_color is None:
            await interaction.response.send_message(
                " Invalid color. Use a 6-digit hex color such as `#8B5CF6`.",
                ephemeral=True,
            )
            return

        pfp = str(self.pfp.value).strip()
        banner = str(self.banner.value).strip()

        if pfp and not valid_url(pfp):
            await interaction.response.send_message(
                " Your PFP URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        if banner and not valid_url(banner):
            await interaction.response.send_message(
                " Your banner URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        profile["color"] = new_color
        profile["image"] = pfp
        profile["banner"] = banner

        await save_data()

        await interaction.response.send_message(
            " Your OC Book appearance has been updated!\n\n"
            "Tip: For Tumblr/Pinterest, use **Copy Image Address** rather "
            "than the normal post/pin URL when possible.",
            ephemeral=True,
        )

class WorldAppearanceModal(discord.ui.Modal, title=" Innerworld Appearance"):
    color = discord.ui.TextInput(
        label="Innerworld Color",
        placeholder="Hex color, e.g. #2B8C85",
        max_length=7,
        required=False,
    )

    pfp = discord.ui.TextInput(
        label="Innerworld PFP URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    banner = discord.ui.TextInput(
        label="Innerworld Banner URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

        world = get_book(owner.id)["world"]
        self.color.default = world.get("color", "#2B8C85")
        self.pfp.default = world.get("image", "")
        self.banner.default = world.get("banner", "")

    async def on_submit(self, interaction):
        world = get_book(self.owner.id)["world"]

        new_color = normalize_hex(self.color.value, "#2B8C85")

        if new_color is None:
            await interaction.response.send_message(
                " Invalid color. Use a 6-digit hex color such as `#2B8C85`.",
                ephemeral=True,
            )
            return

        pfp = str(self.pfp.value).strip()
        banner = str(self.banner.value).strip()

        if pfp and not valid_url(pfp):
            await interaction.response.send_message(
                " Your innerworld PFP URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        if banner and not valid_url(banner):
            await interaction.response.send_message(
                " Your innerworld banner URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        world["color"] = new_color
        world["image"] = pfp
        world["banner"] = banner

        await save_data()

        await interaction.response.send_message(
            "[WORLD] Your innerworld appearance has been updated!",
            ephemeral=True,
        )

class OCAppearanceModal(discord.ui.Modal, title=" OC Appearance"):
    color = discord.ui.TextInput(
        label="OC Color",
        placeholder="Hex color, e.g. #F97316",
        max_length=7,
        required=False,
    )

    pfp = discord.ui.TextInput(
        label="OC PFP URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    banner = discord.ui.TextInput(
        label="OC Banner URL",
        placeholder="Paste a direct HTTPS image URL",
        max_length=500,
        required=False,
    )

    def __init__(self, owner, oc_key, oc):
        super().__init__()
        self.owner = owner
        self.oc_key = oc_key

        self.color.default = oc.get("color", "#5865F2")
        self.pfp.default = oc.get("image", "")
        self.banner.default = oc.get("banner", "")

    async def on_submit(self, interaction):
        book = get_book(self.owner.id)
        oc = book["ocs"].get(self.oc_key)

        if oc is None:
            await interaction.response.send_message(
                " That OC no longer exists.",
                ephemeral=True,
            )
            return

        new_color = normalize_hex(self.color.value, "#5865F2")

        if new_color is None:
            await interaction.response.send_message(
                " Invalid color. Use a 6-digit hex color such as `#F97316`.",
                ephemeral=True,
            )
            return

        pfp = str(self.pfp.value).strip()
        banner = str(self.banner.value).strip()

        if pfp and not valid_url(pfp):
            await interaction.response.send_message(
                " Your OC PFP URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        if banner and not valid_url(banner):
            await interaction.response.send_message(
                " Your OC banner URL must start with `http://` or `https://`.",
                ephemeral=True,
            )
            return

        oc["color"] = new_color
        oc["image"] = pfp
        oc["banner"] = banner

        await save_data()

        await interaction.response.send_message(
            f" **{oc['name']}**'s appearance has been updated!\n\n"
            "Tip: For Tumblr/Pinterest, use **Copy Image Address** "
            "when possible.",
            ephemeral=True,
        )

class WorldModal(discord.ui.Modal, title="Edit World Settings"):
    name = discord.ui.TextInput(
        label="World Name",
        placeholder="e.g. Elysium, Earth-09, The Void...",
        max_length=100,
        required=False,
    )

    genre = discord.ui.TextInput(
        label="Genre",
        placeholder="e.g. Fantasy / Sci-Fi / Horror",
        max_length=200,
        required=False,
    )

    setting = discord.ui.TextInput(
        label="Setting",
        placeholder="Where and when does this world take place?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    lore = discord.ui.TextInput(
        label="Lore",
        placeholder="Important lore and background information...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    rules = discord.ui.TextInput(
        label="Rules / Notes",
        placeholder="World rules, boundaries, or other notes...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

        world = get_book(owner.id)["world"]

        self.name.default = world["name"]
        self.genre.default = world["genre"]
        self.setting.default = world["setting"]
        self.lore.default = world["lore"]
        self.rules.default = world["rules"]

    async def on_submit(self, interaction):
        world = get_book(self.owner.id)["world"]

        world["name"] = str(self.name.value).strip()
        world["genre"] = str(self.genre.value).strip()
        world["setting"] = str(self.setting.value).strip()
        world["lore"] = str(self.lore.value).strip()
        world["rules"] = str(self.rules.value).strip()

        await save_data()

        await interaction.response.send_message(
            " Your world settings have been updated.",
            ephemeral=True,
        )

class OCModal(discord.ui.Modal, title="Add / Edit OC"):
    name = discord.ui.TextInput(
        label="OC Name",
        placeholder="Character name",
        max_length=100,
        required=True,
    )

    age = discord.ui.TextInput(
        label="Age",
        placeholder="Age or age range",
        max_length=100,
        required=False,
    )

    pronouns = discord.ui.TextInput(
        label="Pronouns",
        placeholder="e.g. she/her",
        max_length=100,
        required=False,
    )

    personality = discord.ui.TextInput(
        label="Personality",
        placeholder="Personality, role, or short introduction...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    lore = discord.ui.TextInput(
        label="Lore / Backstory",
        placeholder="Background, story, important details...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(self, owner, existing_key=None, existing_oc=None):
        super().__init__()
        self.owner = owner
        self.existing_key = existing_key

        if existing_oc:
            self.name.default = existing_oc["name"]
            self.age.default = existing_oc["age"]
            self.pronouns.default = existing_oc["pronouns"]
            self.personality.default = existing_oc["personality"]
            self.lore.default = existing_oc["lore"]

        if existing_key:
            self.title = "Edit OC"

    async def on_submit(self, interaction):
        book = get_book(self.owner.id)
        new_name = str(self.name.value).strip()

        if self.existing_key:
            old_data = book["ocs"].get(self.existing_key)

            if old_data is None:
                await interaction.response.send_message(
                    " This OC no longer exists.",
                    ephemeral=True,
                )
                return

            oc = old_data
            old_key = self.existing_key

        else:
            oc = {
                "name": new_name,
                "age": "",
                "pronouns": "",
                "personality": "",
                "appearance": "",
                "lore": "",
                "likes": "",
                "dislikes": "",
                "abilities": "",
                "relationships": "",
                "notes": "",
                "image": "",
                "banner": "",
                "color": "#5865F2",
            }
            old_key = None

        oc["name"] = new_name
        oc["age"] = str(self.age.value).strip()
        oc["pronouns"] = str(self.pronouns.value).strip()
        oc["personality"] = str(self.personality.value).strip()
        oc["lore"] = str(self.lore.value).strip()

        new_key = normalize_name(new_name)

        if old_key and old_key != new_key:
            book["ocs"].pop(old_key, None)

        book["ocs"][new_key] = oc

        await save_data()

        await interaction.response.send_message(
            f" **{new_name}** has been saved to your OC Book.",
            ephemeral=True,
        )

# ============================================================
# COMMAND HELP / CATEGORIES
# ============================================================

COMMAND_CATEGORIES = {
    " OC MANAGEMENT": {
        "ocbook": ("Open an OC Book.", f"{PREFIX}ocbook [@user]"),
        "ocinfo": ("View someone's public OC profile.", f"{PREFIX}ocinfo [@user]"),
        "oclist": ("Browse someone's OC list.", f"{PREFIX}oclist [@user]"),
        "ocpeek": ("View a specific OC.", f"{PREFIX}ocpeek [@user] <OC Name>"),
        "ocadd": ("Create a new OC.", f'{PREFIX}ocadd "Nova"'),
        "ocdelete": ("Delete one of your OCs.", f"{PREFIX}ocdelete Nova"),
        "ocdeleteall": ("Delete all of your OCs at once.", f"{PREFIX}ocdeleteall"),
        "ocsetup": ("Open your OC management panel.", f"{PREFIX}ocsetup"),
    },
    "? OC SHARING": {
        "ocgive": ("Give one of your OCs to another member.", f"{PREFIX}ocgive @user Nova"),
        "ocgift": ("Alias for ocgive.", f"{PREFIX}ocgift @user Nova"),
        "octransfer": ("Alias for ocgive.", f"{PREFIX}octransfer @user Nova"),
    },
    "[JSON] OC JSON IMPORT / EXPORT": {
        "ocexport": (
            "Export your entire OC list, or one specific OC, as a JSON file.",
            f"{PREFIX}ocexport [OC Name]",
        ),
        "ocimport": (
            "Import an Archiverist OC JSON file into your OC Book.",
            f"{PREFIX}ocimport + attach .json",
        ),
        "ocjson": (
            "Show the OC JSON import/export guide.",
            f"{PREFIX}ocjson",
        ),
    },
    " PROXY / ROLEPLAY": {
        "proxyadd": ("Assign a proxy trigger to one of your OCs.", f"{PREFIX}proxyadd N: Nova"),
        "proxylist": ("Show your active OC proxies.", f"{PREFIX}proxylist"),
        "proxyremove": ("Remove one of your OC proxy triggers.", f"{PREFIX}proxyremove N:"),
    },
    "[WORLD] WORLD / LORE": {
        "ocworld": ("View or edit an innerworld.", f"{PREFIX}ocworld [@user]"),
    },
    " PERSONAL ROOMS": {
        "setchannel": ("Set the voice channel that triggers room setup. Admin only.", f"{PREFIX}setchannel [voice channel]"),
        "setroomsetup": ("Set the text channel for room setup panels. Admin only.", f"{PREFIX}setroomsetup #channel"),
        "lock": ("Lock your personal room.", f"{PREFIX}lock"),
        "unlock": ("Unlock your personal room.", f"{PREFIX}unlock"),
    },
    " SERVER TOOLS": {
        "setcolor": ("Change the color of a role you currently have.", f"{PREFIX}setcolor @Role #ff55aa"),
    },
}


def add_command_category(embed, category_name, commands_data):
    lines = []
    for command_name, (description, usage) in commands_data.items():
        lines.append(
            f"**`{PREFIX}{command_name}`** - {description}\n"
            f"? `{usage}`"
        )
    embed.add_field(name=category_name, value="\n\n".join(lines), inline=False)


async def send_command_help(ctx, command_name=None):
    if command_name:
        command_name = command_name.lower().strip()
        for category_name, commands_data in COMMAND_CATEGORIES.items():
            if command_name in commands_data:
                description, usage = commands_data[command_name]
                command = bot.get_command(command_name)
                if command is not None and command.help:
                    description = command.help
                embed = make_embed(
                    f"{category_name} - `{PREFIX}{command_name}`",
                    description,
                    discord.Color.blurple(),
                )
                embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
                embed.set_footer(text=f"Use {PREFIX}commands to return to the full command guide.")
                await ctx.send(embed=embed)
                return
        await ctx.send(embed=make_embed(
            " Unknown Command",
            f"`{PREFIX}{command_name}` is not in the command guide.\n\nUse `{PREFIX}commands` to see every category.",
            discord.Color.red(),
        ))
        return

    embed = make_embed(
        "[COMMANDS] ARCHIVERIST COMMANDS",
        f"Everything is organized into categories below.\n\nUse `{PREFIX}commands <command>` for detailed help on one command.",
        discord.Color.blurple(),
    )
    for category_name, commands_data in COMMAND_CATEGORIES.items():
        add_command_category(embed, category_name, commands_data)
    embed.set_footer(text=f"Example: {PREFIX}commands ocgive - {PREFIX}commands proxyadd")
    await ctx.send(embed=embed)


@bot.command(name="commands", aliases=["help", "cmds"])
async def commands_command(ctx, command_name=None):
    await send_command_help(ctx, command_name)


# ============================================================
# EXTERNAL MODULES
# ============================================================



# ============================================================
# BOT EVENTS / STARTUP
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready!")
    print("Personal rooms + interactive OC Books are active.")

# ============================================================
#  PERSONAL ROOM ADMINISTRATION
# ============================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def setchannel(ctx, channel: discord.VoiceChannel = None):
    global TRIGGER_VOICE_CHANNEL_ID

    if channel is None:
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(
                embed=make_embed(
                    " Setup Failed",
                    f"Join a voice channel first, then use `{PREFIX}setchannel`.",
                    discord.Color.red(),
                )
            )
            return

        channel = ctx.author.voice.channel

    TRIGGER_VOICE_CHANNEL_ID = channel.id

    await ctx.send(
        embed=make_embed(
            " Configuration Updated",
            f"Personal rooms will now be created when someone joins "
            f"{channel.mention}.",
            discord.Color.green(),
        )
    )

@bot.command()
async def setcolor(ctx, target_role: discord.Role, hex_code: str):
    if target_role not in ctx.author.roles:
        await ctx.send(
            embed=make_embed(
                " Permission Denied",
                f"You cannot edit **{target_role.name}** because you do not "
                "currently have that role.",
                discord.Color.red(),
            )
        )
        return

    me = ctx.guild.me

    if me is None or not me.guild_permissions.manage_roles:
        await ctx.send(
            embed=make_embed(
                " Bot Permission Missing",
                "I need **Manage Roles** to change role colors.",
                discord.Color.red(),
            )
        )
        return

    if target_role >= me.top_role:
        await ctx.send(
            embed=make_embed(
                "[DENIED] Role Hierarchy Error",
                "My highest role must be **above the target role**.",
                discord.Color.red(),
            )
        )
        return

    clean_hex = hex_code.strip().lstrip("#")

    if not re.fullmatch(r"[0-9a-fA-F]{6}", clean_hex):
        await ctx.send(
            embed=make_embed(
                " Invalid Hex Code",
                f"Example: `{PREFIX}setcolor @YourRole #ff55aa`",
                discord.Color.orange(),
            )
        )
        return

    try:
        color = discord.Color(int(clean_hex, 16))

        await target_role.edit(
            color=color,
            reason=f"Role color updated by {ctx.author}",
        )

        await ctx.send(
            embed=make_embed(
                " Color Updated",
                f"**{target_role.name}** is now `#{clean_hex.upper()}`.",
                color,
            )
        )

    except discord.Forbidden:
        await ctx.send(
            embed=make_embed(
                "[DENIED] Discord Permission Error",
                "Check my **Manage Roles** permission and role hierarchy.",
                discord.Color.red(),
            )
        )

    except discord.HTTPException:
        await ctx.send(
            embed=make_embed(
                " Discord API Error",
                "Discord could not process the role change.",
                discord.Color.red(),
            )
        )

# ============================================================
#  OC PUBLIC VIEWING / MANAGEMENT COMMANDS
# ============================================================

@bot.command()
async def ocbook(ctx, user: discord.Member = None):
    target = user or ctx.author
    get_book(target.id)
    await save_data()

    await ctx.send(
        embed=build_book_embed(target),
        view=OCBookView(
            target,
            ctx.author.id,
        ),
    )

@bot.command()
async def ocinfo(ctx, user: discord.Member = None):
    target = user or ctx.author
    book = get_book(target.id)
    profile = book["profile"]

    embed = make_embed(
        f"[PROFILE] {profile['name'] or target.display_name}",
        profile["about"] or "No public information has been added.",
        discord.Color.blurple(),
    )

    embed.set_author(
        name=target.display_name,
        icon_url=target.display_avatar.url,
    )

    if profile["pronouns"]:
        embed.add_field(
            name="Pronouns",
            value=profile["pronouns"],
            inline=True,
        )

    if profile["status"]:
        embed.add_field(
            name="Status",
            value=profile["status"],
            inline=True,
        )

    if profile["links"]:
        embed.add_field(
            name="Links",
            value=clip(profile["links"]),
            inline=False,
        )

    await ctx.send(embed=embed)

@bot.command()
async def oclist(ctx, user: discord.Member = None):
    target = user or ctx.author

    await ctx.send(
        embed=build_oc_list_embed(target),
        view=OCListView(
            target,
            ctx.author.id,
        ),
    )

@bot.command()
async def ocworld(ctx, user: discord.Member = None):
    target = user or ctx.author

    await ctx.send(
        embed=build_world_embed(target),
        view=OCWorldView(
            target,
            ctx.author.id,
        ),
    )

@bot.command()
async def ocpeek(ctx, *, query: str):
    query = query.strip()
    target = ctx.author

    if ctx.message.mentions:
        target = ctx.message.mentions[0]
        query = re.sub(
            r"<@!?\d+>",
            "",
            query,
            count=1,
        ).strip()

    if not query:
        await ctx.send(
            embed=make_embed(
                " Missing OC Name",
                f"Try `{PREFIX}ocpeek Nova` or "
                f"`{PREFIX}ocpeek @username Nova`.",
                discord.Color.orange(),
            )
        )
        return

    book = get_book(target.id)
    key = normalize_name(query)
    oc = book["ocs"].get(key)

    if oc is None:
        matches = [
            data
            for data in book["ocs"].values()
            if query.lower() in data["name"].lower()
        ]

        if len(matches) == 1:
            oc = matches[0]
        else:
            await ctx.send(
                embed=make_embed(
                    "OC Not Found",
                    f"I couldn't find **{query}** in "
                    f"{target.display_name}'s OC Book.\n\n"
                    f"Use `{PREFIX}oclist @{target.display_name}` to browse their characters.",
                    discord.Color.red(),
                )
            )
            return

    oc_key = normalize_name(oc["name"])
    profile_view = OCProfileView(target, ctx.author.id, oc_key)
    if layout_is_enabled(oc):
        embed, file = await custom_oc_render(target, oc)
        if embed:
            await ctx.send(embed=embed, file=file, view=profile_view)
            return
    await ctx.send(embed=build_oc_embed(target, oc), view=profile_view)

@bot.command()
async def ocadd(ctx, *, name: str):
    name = name.strip().strip('"').strip("'")

    if not name:
        await ctx.send(
            embed=make_embed(
                " Missing Name",
                f"Example: `{PREFIX}ocadd Nova`",
                discord.Color.orange(),
            )
        )
        return

    book = get_book(ctx.author.id)
    key = normalize_name(name)

    if key in book["ocs"]:
        await ctx.send(
            embed=make_embed(
                " OC Already Exists",
                f"**{name}** already exists in your OC Book.\n"
                f"Use the **Edit OC** button from `{PREFIX}ocpeek {name}`.",
                discord.Color.orange(),
            )
        )
        return

    book["ocs"][key] = {
        "name": name,
        "age": "",
        "pronouns": "",
        "personality": "",
        "appearance": "",
        "lore": "",
        "likes": "",
        "dislikes": "",
        "abilities": "",
        "relationships": "",
        "notes": "",
        "image": "",
        "banner": "",
        "color": "#5865F2",
    }

    await save_data()

    embed = make_embed(
        " OC Created",
        f"**{name}** has been added to your OC Book.\n\n"
        "Open the button below to fill in the character information.",
        discord.Color.green(),
    )

    class EditNewOCView(discord.ui.View):
        def __init__(self, owner, oc_key):
            super().__init__(timeout=300)
            self.owner = owner
            self.oc_key = oc_key

        @discord.ui.button(
            label="Edit OC",
            style=discord.ButtonStyle.success,
        )
        async def edit(self, interaction, button):
            if interaction.user.id != self.owner.id:
                await interaction.response.send_message(
                    " Only the owner can edit this OC.",
                    ephemeral=True,
                )
                return

            oc = get_book(self.owner.id)["ocs"].get(self.oc_key)

            if not oc:
                await interaction.response.send_message(
                    " This OC no longer exists.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_modal(
                OCModal(
                    self.owner,
                    existing_key=self.oc_key,
                    existing_oc=oc,
                )
            )

    await ctx.send(
        embed=embed,
        view=EditNewOCView(ctx.author, key),
    )

@bot.command()
async def ocdelete(ctx, *, name: str):
    book = get_book(ctx.author.id)
    key = normalize_name(name)

    if key not in book["ocs"]:
        await ctx.send(
            embed=make_embed(
                " OC Not Found",
                f"I couldn't find **{name}** in your OC Book.",
                discord.Color.red(),
            )
        )
        return

    display_name = book["ocs"][key]["name"]
    del book["ocs"][key]

    await save_data()

    await ctx.send(
        embed=make_embed(
            "OC Deleted",
            f"**{display_name}** has been removed from your OC Book.",
            discord.Color.red(),
        )
    )

@bot.command()
async def ocdeleteall(ctx):
    book = get_book(ctx.author.id)
    ocs = book["ocs"]

    if not ocs:
        await ctx.send(
            embed=make_embed(
                " No OCs Found",
                "You don't have any OCs to delete.",
                discord.Color.orange(),
            )
        )
        return

    class DeleteAllOCView(discord.ui.View):
        def __init__(self, owner):
            super().__init__(timeout=60)
            self.owner = owner

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner.id:
                await interaction.response.send_message(
                    " Only the owner can confirm this.",
                    ephemeral=True,
                )
                return False
            return True

        @discord.ui.button(
            label="Delete All OCs",
            style=discord.ButtonStyle.danger,
        )
        async def confirm(self, interaction, button):
            book = get_book(self.owner.id)
            count = len(book["ocs"])

            if count == 0:
                await interaction.response.edit_message(
                    embed=make_embed(
                        " No OCs Found",
                        "You don't have any OCs to delete.",
                        discord.Color.orange(),
                    ),
                    view=None,
                )
                return

            book["ocs"].clear()

            await save_data()

            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(
                embed=make_embed(
                    "All OCs Deleted",
                    f"Successfully deleted **{count} OC(s)** from your OC Book.",
                    discord.Color.red(),
                ),
                view=self,
            )

            self.stop()

        @discord.ui.button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
        )
        async def cancel(self, interaction, button):
            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(
                embed=make_embed(
                    "[CANCELLED] Nothing Deleted",
                    "Your OCs were not changed.",
                    discord.Color.green(),
                ),
                view=self,
            )

            self.stop()

    await ctx.send(
        embed=make_embed(
            "Delete All OCs?",
            f"This will permanently delete **all {len(ocs)} OC(s)** "
            "from your OC Book.\n\n"
            "**This action cannot be undone.**",
            discord.Color.red(),
        ),
        view=DeleteAllOCView(ctx.author),
    )

# ============================================================
# ? OC SHARING / TRANSFER
# ============================================================


class OCGiveView(discord.ui.View):
    """Confirmation UI for transferring an OC to another member."""

    def __init__(self, giver, recipient, oc_key, timeout=120):
        super().__init__(timeout=timeout)
        self.giver = giver
        self.recipient = recipient
        self.oc_key = oc_key

    async def interaction_check(self, interaction):
        if interaction.user.id != self.giver.id:
            await interaction.response.send_message(" Only the current owner can confirm this transfer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Give OC", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        giver_book = get_book(self.giver.id)
        recipient_book = get_book(self.recipient.id)
        oc = giver_book["ocs"].get(self.oc_key)
        if oc is None:
            await interaction.response.edit_message(embed=make_embed(" Transfer Failed", "This OC no longer exists in your OC Book.", discord.Color.red()), view=None)
            return
        if self.oc_key in recipient_book["ocs"]:
            await interaction.response.edit_message(embed=make_embed(" Transfer Failed", f"{self.recipient.mention} already has an OC named **{oc['name']}**.", discord.Color.orange()), view=None)
            return
        recipient_book["ocs"][self.oc_key] = deepcopy(oc)
        for trigger, proxy_key in list(giver_book.get("proxies", {}).items()):
            if proxy_key == self.oc_key:
                giver_book["proxies"].pop(trigger, None)
        giver_book["ocs"].pop(self.oc_key, None)
        await save_data()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=make_embed(
                "? OC Transferred!",
                f"**{oc['name']}** has been transferred successfully.\n\n**Previous owner:** {self.giver.mention}\n**New owner:** {self.recipient.mention}\n\nThe new owner now has full control of the OC, including its profile data, appearance, and custom layout.",
                embed_color(oc.get("color"), discord.Color.green()),
            ),
            view=self,
        )
        try:
            await self.recipient.send(embed=make_embed(
                "? You Received an OC!",
                f"{self.giver.display_name} gave you **{oc['name']}**!\n\nThe OC has been added to your OC Book. You can now edit it and create your own proxy.",
                embed_color(oc.get("color"), discord.Color.green()),
            ))
        except (discord.Forbidden, discord.HTTPException):
            pass
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=make_embed("? Transfer Cancelled", "The OC was not transferred.", discord.Color.red()),
            view=self,
        )
        self.stop()


async def transfer_oc(ctx, recipient, oc_name):
    """Validate and start an OC transfer."""
    if recipient.bot:
        await ctx.send(embed=make_embed(" Invalid Recipient", "You can't give an OC to a bot.", discord.Color.red()))
        return
    if recipient.id == ctx.author.id:
        await ctx.send(embed=make_embed(" Invalid Recipient", "You can't give an OC to yourself.", discord.Color.red()))
        return
    oc_name = oc_name.strip().strip('"').strip("'")
    if not oc_name:
        await ctx.send(embed=make_embed(" Missing OC Name", f"Usage: `{PREFIX}ocgive @user Nova`", discord.Color.orange()))
        return
    giver_book = get_book(ctx.author.id)
    oc_key = normalize_name(oc_name)
    oc = giver_book["ocs"].get(oc_key)
    if oc is None:
        await ctx.send(embed=make_embed(" OC Not Found", f"I couldn't find **{oc_name}** in your OC Book.", discord.Color.red()))
        return
    recipient_book = get_book(recipient.id)
    if oc_key in recipient_book["ocs"]:
        await ctx.send(embed=make_embed(" Duplicate OC", f"{recipient.mention} already has an OC named **{oc['name']}**.", discord.Color.orange()))
        return
    embed = make_embed(
        "? Give OC?",
        f"You are about to give **{oc['name']}** to {recipient.mention}.\n\n### Everything included\n Character information\n PFP and banner\n Color settings\n Custom layout\n Lore and notes\n? Relationships and abilities\n\n**After confirmation, the OC is removed from your OC Book.**\nThe recipient becomes the new owner.",
        embed_color(oc.get("color"), discord.Color.gold()),
    )
    embed.set_footer(text="Only you can confirm or cancel this transfer.")
    await ctx.send(embed=embed, view=OCGiveView(ctx.author, recipient, oc_key))


@bot.command(name="ocgive", aliases=["ocgift", "octransfer"])
async def ocgive(ctx, member: discord.Member, *, oc_name: str):
    """Give an OC to another server member."""
    await transfer_oc(ctx, member, oc_name)


# ============================================================
# OC PROXY / ROLEPLAY
# ============================================================

proxy_webhooks = {}


def get_proxy_for_message(book, content):
    """Return (trigger, oc) for the first matching proxy trigger."""
    for trigger, oc_key in sorted(
        book.get("proxies", {}).items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not content.startswith(trigger):
            continue

        # Avoid treating a longer trigger as a match when another one
        # is more specific, e.g. "E:" before "E:>".
        if isinstance(oc_key, str) and oc_key in book.get("ocs", {}):
            return trigger, book["ocs"][oc_key]

    return None, None


async def get_proxy_webhook(channel):
    """Reuse one bot-owned webhook per channel, creating it if needed."""
    cached = proxy_webhooks.get(channel.id)
    if cached is not None:
        return cached

    webhooks = await channel.webhooks()
    for webhook in webhooks:
        if webhook.user and bot.user and webhook.user.id == bot.user.id:
            proxy_webhooks[channel.id] = webhook
            return webhook

    webhook = await channel.create_webhook(
        name="Archiverist Proxy",
        reason="OC roleplay proxy messages.",
    )
    proxy_webhooks[channel.id] = webhook
    return webhook


@bot.command(name="proxyadd")
async def proxyadd(ctx, trigger: str, *, oc_name: str):
    """Assign a trigger such as E: or an emoji to one of your OCs."""
    trigger = trigger.strip()
    oc_name = oc_name.strip().strip('"').strip("'")

    if not trigger or not oc_name:
        await ctx.send(
            embed=make_embed(
                " Missing Input",
                f"Use `{PREFIX}proxyadd E: Ethan Winslow`",
                discord.Color.red(),
            )
        )
        return

    if len(trigger) > 32 or "\n" in trigger or "\r" in trigger:
        await ctx.send(
            embed=make_embed(
                " Invalid Trigger",
                "Your proxy trigger must be 32 characters or fewer and stay on one line.",
                discord.Color.red(),
            )
        )
        return

    if trigger.startswith(PREFIX):
        await ctx.send(
            embed=make_embed(
                " Invalid Trigger",
                f"Don't use `{PREFIX}` as a proxy trigger because it is reserved for bot commands.",
                discord.Color.red(),
            )
        )
        return

    book = get_book(ctx.author.id)
    oc_key = normalize_name(oc_name)
    oc = book["ocs"].get(oc_key)

    if oc is None:
        await ctx.send(
            embed=make_embed(
                " OC Not Found",
                f"I couldn't find **{oc_name}** in your OC Book.",
                discord.Color.red(),
            )
        )
        return

    # One trigger belongs to one OC for this user.
    book["proxies"][trigger] = oc_key
    await save_data()

    await ctx.send(
        embed=make_embed(
            " Proxy Added",
            f"**{oc['name']}** will now speak when you start a message with `{trigger}`.\n\n"
            f"Example: `{trigger} Hello there!`",
            embed_color(oc.get("color"), discord.Color.green()),
        )
    )


@bot.command(name="proxylist")
async def proxylist(ctx):
    """Show the user's active OC proxy triggers."""
    book = get_book(ctx.author.id)
    proxies = book.get("proxies", {})

    if not proxies:
        await ctx.send(
            embed=make_embed(
                " OC Proxies",
                f"You don't have any proxies yet.\nUse `{PREFIX}proxyadd E: Ethan Winslow` to add one.",
                discord.Color.blurple(),
            )
        )
        return

    lines = []
    for trigger, oc_key in proxies.items():
        oc = book["ocs"].get(oc_key)
        if oc:
            lines.append(f"`{trigger}` ? **{oc['name']}**")

    await ctx.send(
        embed=make_embed(
            " OC Proxies",
            "\n".join(lines) or "No valid proxies found.",
            discord.Color.blurple(),
        )
    )


@bot.command(name="proxyremove")
async def proxyremove(ctx, *, trigger: str):
    """Remove one of the user's OC proxy triggers."""
    trigger = trigger.strip()
    book = get_book(ctx.author.id)

    if trigger not in book.get("proxies", {}):
        await ctx.send(
            embed=make_embed(
                " Proxy Not Found",
                f"`{trigger}` isn't one of your active proxy triggers.",
                discord.Color.red(),
            )
        )
        return

    book["proxies"].pop(trigger, None)
    await save_data()

    await ctx.send(
        embed=make_embed(
            "Proxy Removed",
            f"The `{trigger}` proxy has been removed.",
            discord.Color.green(),
        )
    )


@bot.event
async def on_message(message):
    # Never proxy bots/webhooks, including Archiverist's own webhook messages.
    if message.author.bot or message.webhook_id:
        await bot.process_commands(message)
        return

    # Commands still work normally.
    if message.content.startswith(PREFIX):
        await bot.process_commands(message)
        return

    book = get_book(message.author.id)
    trigger, oc = get_proxy_for_message(book, message.content)

    if trigger is None or oc is None:
        await bot.process_commands(message)
        return

    # Everything after the trigger becomes the OC's message.
    content = message.content[len(trigger):].lstrip()
    if not content:
        return

    try:
        webhook = await get_proxy_webhook(message.channel)

        webhook_kwargs = {
            "content": content,
            "username": oc.get("name") or "OC",
            "allowed_mentions": discord.AllowedMentions.none(),
            "wait": True,
        }

        avatar_url = str(oc.get("image") or "").strip()
        if valid_url(avatar_url):
            webhook_kwargs["avatar_url"] = avatar_url

        await webhook.send(**webhook_kwargs)
        await message.delete()

    except discord.Forbidden:
        await message.channel.send(
            f" I need **Manage Webhooks** and **Manage Messages** here to use OC proxies.",
            delete_after=8,
        )
    except discord.HTTPException as error:
        print(f" OC proxy failed in #{message.channel}: {error}")


@bot.command()
async def ocsetup(ctx):
    embed = make_embed(
        "OC Book Management",
        "Use the commands and buttons below to manage your OC Book.",
        discord.Color.gold(),
    )

    embed.add_field(
        name="[PROFILE] Profile",
        value=(
            f"Use `{PREFIX}ocbook` and press **Edit Book** to change "
            "your public information."
        ),
        inline=False,
    )

    embed.add_field(
        name=" Characters",
        value=(
            f"Use `{PREFIX}ocadd Name` to create an OC.\n"
            "Then use **Edit OC** to fill in the details."
        ),
        inline=False,
    )

    embed.add_field(
        name="[WORLD] Innerworld",
        value=(
            f"Use `{PREFIX}ocworld` and press **Edit World** "
            "to customize your setting."
        ),
        inline=False,
    )

    embed.add_field(
        name=" Appearance",
        value=(
            "Customize the **color, PFP, and banner** for your Book, "
            "each OC, and your Innerworld. "
            "Open the relevant page and press ** Appearance**."
        ),
        inline=False,
    )

    embed.add_field(
        name="Public Viewing",
        value=(
            f"`{PREFIX}ocbook @username`\n"
            f"`{PREFIX}ocpeek OC Name`"
        ),
        inline=False,
    )

    await ctx.send(
        embed=embed,
        view=OCBookView(
            ctx.author,
            ctx.author.id,
        ),
    )

# ============================================================
#  PERSONAL ROOM SETUP UI
# ============================================================

ROOM_SETUP_TEXT_CHANNEL_ID = None
pending_room_setups = {}

class RoomSetupState:
    def __init__(self, member):
        self.member = member
        self.text_count = 2
        self.voice_count = 1
        self.text_names = []
        self.voice_names = []

    def ensure_names(self):
        while len(self.text_names) < self.text_count:
            self.text_names.append(f"text-{len(self.text_names) + 1}")
        while len(self.voice_names) < self.voice_count:
            self.voice_names.append(f"vc-{len(self.voice_names) + 1}")
        self.text_names = self.text_names[:self.text_count]
        self.voice_names = self.voice_names[:self.voice_count]

class RoomCountModal(discord.ui.Modal, title=" Personal Room Setup"):
    text_count = discord.ui.TextInput(
        label="Number of Text Channels",
        placeholder="0 - 5 (default: 2)",
        max_length=1,
        required=True,
    )
    voice_count = discord.ui.TextInput(
        label="Number of Voice Channels",
        placeholder="0 - 5 (default: 1)",
        max_length=1,
        required=True,
    )

    def __init__(self, member):
        super().__init__()
        self.member = member
        state = pending_room_setups.get((member.guild.id, member.id))
        if state:
            self.text_count.default = str(state.text_count)
            self.voice_count.default = str(state.voice_count)
        else:
            self.text_count.default = "2"
            self.voice_count.default = "1"

    async def on_submit(self, interaction):
        try:
            text_count = int(str(self.text_count.value).strip())
            voice_count = int(str(self.voice_count.value).strip())
        except ValueError:
            await interaction.response.send_message(
                " Please enter whole numbers from 0 to 5.",
                ephemeral=True,
            )
            return

        if not 0 <= text_count <= 5 or not 0 <= voice_count <= 5:
            await interaction.response.send_message(
                " Each channel count must be between **0 and 5**.",
                ephemeral=True,
            )
            return

        if text_count == 0 and voice_count == 0:
            await interaction.response.send_message(
                " You need at least one text or voice channel.",
                ephemeral=True,
            )
            return

        state = pending_room_setups.setdefault(
            (self.member.guild.id, self.member.id),
            RoomSetupState(self.member),
        )
        state.text_count = text_count
        state.voice_count = voice_count
        state.ensure_names()

        await interaction.response.edit_message(
            embed=build_room_setup_embed(self.member, state),
            view=RoomSetupView(self.member),
        )

class TextNamesModal(discord.ui.Modal, title="Name Your Text Channels"):
    name1 = discord.ui.TextInput(label="Text Channel 1", max_length=100, required=False)
    name2 = discord.ui.TextInput(label="Text Channel 2", max_length=100, required=False)
    name3 = discord.ui.TextInput(label="Text Channel 3", max_length=100, required=False)
    name4 = discord.ui.TextInput(label="Text Channel 4", max_length=100, required=False)
    name5 = discord.ui.TextInput(label="Text Channel 5", max_length=100, required=False)

    def __init__(self, member):
        super().__init__()
        self.member = member
        state = pending_room_setups[(member.guild.id, member.id)]
        state.ensure_names()
        fields = [self.name1, self.name2, self.name3, self.name4, self.name5]
        for i, field in enumerate(fields):
            field.default = state.text_names[i] if i < state.text_count else ""
            field.required = i < state.text_count
            if i >= state.text_count:
                field.label = f"Text Channel {i + 1} (unused)"

    async def on_submit(self, interaction):
        state = pending_room_setups[(self.member.guild.id, self.member.id)]
        fields = [self.name1, self.name2, self.name3, self.name4, self.name5]
        names = []
        for i in range(state.text_count):
            name = str(fields[i].value).strip()
            if not name:
                await interaction.response.send_message(
                    f" Text Channel {i + 1} needs a name.",
                    ephemeral=True,
                )
                return
            names.append(name)
        state.text_names = names
        await interaction.response.edit_message(
            embed=build_room_setup_embed(self.member, state),
            view=RoomSetupView(self.member),
        )

class VoiceNamesModal(discord.ui.Modal, title="Name Your Voice Channels"):
    name1 = discord.ui.TextInput(label="Voice Channel 1", max_length=100, required=False)
    name2 = discord.ui.TextInput(label="Voice Channel 2", max_length=100, required=False)
    name3 = discord.ui.TextInput(label="Voice Channel 3", max_length=100, required=False)
    name4 = discord.ui.TextInput(label="Voice Channel 4", max_length=100, required=False)
    name5 = discord.ui.TextInput(label="Voice Channel 5", max_length=100, required=False)

    def __init__(self, member):
        super().__init__()
        self.member = member
        state = pending_room_setups[(member.guild.id, member.id)]
        state.ensure_names()
        fields = [self.name1, self.name2, self.name3, self.name4, self.name5]
        for i, field in enumerate(fields):
            field.default = state.voice_names[i] if i < state.voice_count else ""
            field.required = i < state.voice_count
            if i >= state.voice_count:
                field.label = f"Voice Channel {i + 1} (unused)"

    async def on_submit(self, interaction):
        state = pending_room_setups[(self.member.guild.id, self.member.id)]
        fields = [self.name1, self.name2, self.name3, self.name4, self.name5]
        names = []
        for i in range(state.voice_count):
            name = str(fields[i].value).strip()
            if not name:
                await interaction.response.send_message(
                    f" Voice Channel {i + 1} needs a name.",
                    ephemeral=True,
                )
                return
            names.append(name)
        state.voice_names = names
        await interaction.response.edit_message(
            embed=build_room_setup_embed(self.member, state),
            view=RoomSetupView(self.member),
        )

def build_room_setup_embed(member, state):
    state.ensure_names()
    text = "\n".join(f"- {name}" for name in state.text_names) or "None"
    voice = "\n".join(f"- {name}" for name in state.voice_names) or "None"

    embed = make_embed(
        " Personal Room Setup",
        f"Welcome, {member.mention}! Choose your channels before I create your room.",
        discord.Color.gold(),
    )
    embed.add_field(
        name=f"Text Channels ({state.text_count})",
        value=text,
        inline=True,
    )
    embed.add_field(
        name=f"Voice Channels ({state.voice_count})",
        value=voice,
        inline=True,
    )
    embed.add_field(
        name="How it works",
        value=(
            "1. Choose how many channels you want.\n"
            "2. Edit their names.\n"
            "3. Press **Create My Room**.\n\n"
            "Nothing is created until you confirm."
        ),
        inline=False,
    )
    return embed

class RoomSetupView(discord.ui.View):
    def __init__(self, member, timeout=600):
        super().__init__(timeout=timeout)
        self.member = member

    async def interaction_check(self, interaction):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                " This room setup belongs to the person who joined the setup VC.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Channel Counts", style=discord.ButtonStyle.primary)
    async def counts(self, interaction, button):
        await interaction.response.send_modal(RoomCountModal(self.member))

    @discord.ui.button(label="Name Text", style=discord.ButtonStyle.secondary)
    async def text_names(self, interaction, button):
        state = pending_room_setups.get((self.member.guild.id, self.member.id))
        if not state or state.text_count == 0:
            await interaction.response.send_message(
                "You selected 0 text channels.", ephemeral=True
            )
            return
        await interaction.response.send_modal(TextNamesModal(self.member))

    @discord.ui.button(label="Name Voice", style=discord.ButtonStyle.secondary)
    async def voice_names(self, interaction, button):
        state = pending_room_setups.get((self.member.guild.id, self.member.id))
        if not state or state.voice_count == 0:
            await interaction.response.send_message(
                "You selected 0 voice channels.", ephemeral=True
            )
            return
        await interaction.response.send_modal(VoiceNamesModal(self.member))

    @discord.ui.button(label="Create My Room", style=discord.ButtonStyle.success, row=1)
    async def create_room(self, interaction, button):
        state = pending_room_setups.get((self.member.guild.id, self.member.id))
        if not state:
            await interaction.response.send_message(
                " Your setup session expired. Please join the setup VC again.",
                ephemeral=True,
            )
            return

        state.ensure_names()
        await interaction.response.defer()

        try:
            result = await create_personal_room(self.member, state)
        except Exception as error:
            print(f" Unexpected room creation error: {error}")
            await interaction.followup.send(
                " Something went wrong while creating your room. Check the bot console.",
                ephemeral=True,
            )
            return

        if result:
            pending_room_setups.pop((self.member.guild.id, self.member.id), None)
            await interaction.edit_original_response(
                embed=make_embed(
                    "Personal Room Created",
                    result,
                    discord.Color.green(),
                ),
                view=None,
            )

async def create_room_setup_panel(member):
    guild = member.guild
    channel = None

    if ROOM_SETUP_TEXT_CHANNEL_ID:
        channel = guild.get_channel(ROOM_SETUP_TEXT_CHANNEL_ID)

    if channel is None:
        channel = guild.system_channel

    if channel is None or not isinstance(channel, discord.TextChannel):
        print(
            f"No room setup text channel is configured for {guild.name}. "
            f"Use !setroomsetup #channel."
        )
        return

    state = pending_room_setups.setdefault(
        (guild.id, member.id),
        RoomSetupState(member),
    )
    state.ensure_names()

    try:
        await channel.send(
            content=member.mention,
            embed=build_room_setup_embed(member, state),
            view=RoomSetupView(member),
        )
    except discord.HTTPException as error:
        print(f" Could not post room setup panel: {error}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setroomsetup(ctx, channel: discord.TextChannel):
    global ROOM_SETUP_TEXT_CHANNEL_ID
    ROOM_SETUP_TEXT_CHANNEL_ID = channel.id

    await ctx.send(
        embed=make_embed(
            " Room Setup Channel Updated",
            f"When someone joins the trigger VC, their setup panel will appear in {channel.mention}.\n\n"
            "Discord does not allow a bot to open a Modal directly from a voice-state event, "
            "so the user will click the setup panel's button to open the popup.",
            discord.Color.green(),
        )
    )

async def create_personal_room(member, state):
    guild = member.guild

    category_name = f"{member.display_name.upper()}'S ROOM"
    existing_category = discord.utils.get(guild.categories, name=category_name)

    if existing_category is not None:
        existing_vc = next(
            (channel for channel in existing_category.voice_channels),
            None,
        )
        if existing_vc:
            try:
                await member.move_to(existing_vc)
            except discord.HTTPException:
                pass
        return "You already have a personal room. I moved you back into it."

    try:
        role_name = f"{member.display_name}'s Role"
        new_role = await guild.create_role(
            name=role_name,
            reason="Personal room setup.",
        )
        await member.add_roles(new_role, reason="Personal room setup.")
    except discord.Forbidden as error:
        print(f" Error creating/assigning personal role: {error}")
        return None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
        ),
        new_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
            manage_channels=True,
            manage_permissions=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
            manage_channels=True,
            manage_permissions=True,
            move_members=True,
        ),
    }

    try:
        category = await guild.create_category(
            name=category_name,
            overwrites=overwrites,
            reason="Personal room setup.",
        )

        created_text = []
        created_voice = []

        for name in state.text_names:
            created_text.append(
                await guild.create_text_channel(
                    name=sanitize_channel_name(name),
                    category=category,
                    reason="Personal room setup.",
                )
            )

        for name in state.voice_names:
            created_voice.append(
                await guild.create_voice_channel(
                    name=sanitize_channel_name(name),
                    category=category,
                    reason="Personal room setup.",
                )
            )

        if created_voice:
            try:
                await member.move_to(created_voice[0])
            except discord.HTTPException as error:
                print(f"Could not move {member}: {error}")

        if created_text:
            welcome_embed = make_embed(
                " Welcome to Your Personal Suite!",
                f"Hello {member.mention}! Your personal room has been created.",
                discord.Color.gold(),
            )
            welcome_embed.add_field(
                name=" Your OC Book",
                value=(
                    f"Create your profile and characters with `{PREFIX}ocsetup`.\n"
                    f"Others can view it with `{PREFIX}ocbook @username`."
                ),
                inline=False,
            )
            welcome_embed.add_field(
                name="OC Commands",
                value=(
                    f"`{PREFIX}ocbook @username` - Open an OC Book\n"
                    f"`{PREFIX}ocpeek OC Name` - Peek at an OC\n"
                    f"`{PREFIX}oclist @username` - View their OC list\n"
                    f"`{PREFIX}ocworld @username` - View their world"
                ),
                inline=False,
            )
            welcome_embed.add_field(
                name=" Role Color",
                value=f"`{PREFIX}setcolor {new_role.mention} #ff55aa`",
                inline=False,
            )
            welcome_embed.add_field(
                name=" Privacy",
                value=f"`{PREFIX}lock` - Lock your room\n`{PREFIX}unlock` - Unlock your room",
                inline=False,
            )
            await created_text[0].send(
                content=member.mention,
                embed=welcome_embed,
            )

        summary = (
            f"Your room is ready in **{category.name}**.\n\n"
            f"Text channels: **{len(created_text)}**\n"
            f"Voice channels: **{len(created_voice)}**"
        )
        print(f" Created custom personal room for {member} ({guild.name})")
        return summary

    except discord.Forbidden as error:
        print(f" Permission error creating room: {error}")
        return None
    except discord.HTTPException as error:
        print(f" Discord API error creating room: {error}")
        return None

def sanitize_channel_name(name):
    name = re.sub(r"\s+", "-", name.strip())
    name = re.sub(r"[^\w\-]+", "", name, flags=re.UNICODE)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:100] or "channel"

# ============================================================
# VOICE ROOM TRIGGER
# ============================================================

@bot.event
async def on_voice_state_update(member, before, after):
    global TRIGGER_VOICE_CHANNEL_ID

    if TRIGGER_VOICE_CHANNEL_ID is None:
        return
    if after.channel is None:
        return
    if before.channel and before.channel.id == after.channel.id:
        return
    if after.channel.id != TRIGGER_VOICE_CHANNEL_ID:
        return

    guild = member.guild
    category_name = f"{member.display_name.upper()}'S ROOM"
    existing_category = discord.utils.get(guild.categories, name=category_name)

    if existing_category is not None:
        existing_vc = next(
            (channel for channel in existing_category.voice_channels),
            None,
        )
        if existing_vc:
            try:
                await member.move_to(existing_vc)
            except discord.HTTPException as error:
                print(f"Could not move {member}: {error}")
        return

    key = (guild.id, member.id)
    if key in pending_room_setups:
        return

    await create_room_setup_panel(member)

def get_personal_category(ctx):
    category_name = f"{ctx.author.display_name.upper()}'S ROOM"

    return discord.utils.get(
        ctx.guild.categories,
        name=category_name,
    )

# ============================================================
#  PERSONAL ROOM PRIVACY
# ============================================================

@bot.command()
async def lock(ctx):
    category = get_personal_category(ctx)

    if category is None or ctx.channel.category != category:
        await ctx.send(
            embed=make_embed(
                " Wrong Channel",
                "You can only use this command inside your personal room.",
                discord.Color.red(),
            )
        )
        return

    try:
        await category.set_permissions(
            ctx.guild.default_role,
            view_channel=False,
            connect=False,
        )

        await ctx.send(
            embed=make_embed(
                "Space Locked",
                "Your personal room is now hidden from the default server role.",
                discord.Color.orange(),
            )
        )

    except discord.Forbidden:
        await ctx.send(
            embed=make_embed(
                " Permission Error",
                "I cannot change this category's permissions.",
                discord.Color.red(),
            )
        )

@bot.command()
async def unlock(ctx):
    category = get_personal_category(ctx)

    if category is None or ctx.channel.category != category:
        await ctx.send(
            embed=make_embed(
                "Wrong Channel",
                "You can only use this command inside your personal room.",
                discord.Color.red(),
            )
        )
        return

    try:
        await category.set_permissions(
            ctx.guild.default_role,
            view_channel=True,
            connect=True,
        )

        await ctx.send(
            embed=make_embed(
                "Space Unlocked",
                "Your personal room is visible to the default server role again.",
                discord.Color.green(),
            )
        )

    except discord.Forbidden:
        await ctx.send(
            embed=make_embed(
                " Permission Error",
                "I cannot change this category's permissions.",
                discord.Color.red(),
            )
        )

# ============================================================
# ? MEMBER DEPARTURE HANDLING
# ============================================================

@bot.event
async def on_member_remove(member):
    guild = member.guild
    category_name = f"{member.display_name.upper()}'S ROOM"

    category = discord.utils.get(
        guild.categories,
        name=category_name,
    )

    if category is None:
        print(f"{member} left, but no personal room was found.")
        return

    try:
        await category.set_permissions(
            guild.default_role,
            view_channel=False,
            send_messages=False,
            connect=False,
            speak=False,
        )

        print(
            f" Hidden personal room for {member} "
            f"after they left {guild.name}."
        )

    except discord.Forbidden:
        print(
            f" Could not hide {member}'s personal room. "
            "Check Manage Channels and Manage Permissions."
        )

    except discord.HTTPException as error:
        print(
            f" Discord API error while hiding {member}'s room: {error}"
        )

# ============================================================
# ERROR HANDLING
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        command = ctx.command

        embed = make_embed(
            " Missing Input",
            f"You didn't provide everything required for "
            f"`{PREFIX}{command.name}`.",
            discord.Color.orange(),
        )

        if command and command.signature:
            embed.add_field(
                name="Correct Format",
                value=f"`{PREFIX}{command.name} {command.signature}`",
                inline=False,
            )

        await ctx.send(embed=embed)
        return

    if isinstance(error, commands.BadArgument):
        command = ctx.command

        embed = make_embed(
            " Invalid Input",
            "I couldn't understand one of the values you entered.",
            discord.Color.orange(),
        )

        if command and command.signature:
            embed.add_field(
                name="Correct Format",
                value=f"`{PREFIX}{command.name} {command.signature}`",
                inline=False,
            )

        await ctx.send(embed=embed)
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            embed=make_embed(
                "PERMISSION DENIED",
                "You don't have permission to use this command.",
                discord.Color.red(),
            )
        )
        return

    if isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)

        await ctx.send(
            embed=make_embed(
                " Bot Permission Missing",
                f"I need:\n`{missing}`",
                discord.Color.red(),
            )
        )
        return

    print(
        f" Unhandled command error in "
        f"{getattr(ctx.command, 'name', 'unknown')}: {error}"
    )


# ============================================================
# [JSON] OC JSON MODULE
# ============================================================

setup_oc_json_commands(
    bot=bot,
    get_book=get_book,
    save_data=save_data,
    normalize_name=normalize_name,
    make_embed=make_embed,
)

bot.run(TOKEN)