import io
import json
from copy import deepcopy

import discord


MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_OCS_PER_IMPORT = 100
JSON_FORMAT = "archiverist-oc-list"
JSON_VERSION = 1


def _export_payload(ocs):
    return {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "ocs": {
            str(key): deepcopy(oc)
            for key, oc in ocs.items()
            if isinstance(oc, dict)
        },
    }


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("The JSON root must be an object.")

    if payload.get("format") != JSON_FORMAT:
        raise ValueError(
            "This is not an Archiverist OC List JSON file."
        )

    version = payload.get("version", 1)

    if not isinstance(version, int):
        raise ValueError("The JSON version must be a number.")

    if version > JSON_VERSION:
        raise ValueError(
            f"This file uses unsupported OC List version {version}."
        )

    ocs = payload.get("ocs")

    if not isinstance(ocs, dict):
        raise ValueError(
            'The JSON file must contain an "ocs" object.'
        )

    if len(ocs) > MAX_OCS_PER_IMPORT:
        raise ValueError(
            f"An import can contain at most {MAX_OCS_PER_IMPORT} OCs."
        )

    cleaned = {}

    for key, oc in ocs.items():
        if not isinstance(key, str):
            raise ValueError("OC keys must be strings.")

        if not isinstance(oc, dict):
            raise ValueError(
                f"OC `{key}` must contain an object."
            )

        name = str(oc.get("name", "")).strip()

        if not name:
            raise ValueError(
                f"OC `{key}` is missing its name."
            )

        cleaned[key] = deepcopy(oc)

    return cleaned


def _safe_filename(name, fallback="oc_list"):
    cleaned = "".join(
        char
        for char in str(name)
        if char.isalnum() or char in "-_ "
    ).strip()

    cleaned = cleaned.replace(" ", "_")

    return cleaned[:80] or fallback


def setup_oc_json_commands(
    bot,
    get_book,
    save_data,
    normalize_name,
    make_embed,
):
    """
    Register the OC JSON commands on the existing Archiverist bot.

    This function must be called after get_book(), save_data(),
    normalize_name(), and make_embed() have been defined.
    """

    # Prevent duplicate registration if main.py is reloaded.
    if bot.get_command("ocexport") is not None:
        return

    # ========================================================
    # 📤 EXPORT
    # ========================================================

    @bot.command(
        name="ocexport",
        aliases=["ocexportjson", "ocjsonexport"],
        help="Export your entire OC list, or one specific OC, as JSON.",
    )
    async def ocexport(ctx, *, oc_name: str = None):
        book = get_book(ctx.author.id)
        ocs = book.get("ocs", {})

        if not ocs:
            await ctx.send(
                embed=make_embed(
                    "📦 OC Export",
                    "Your OC Book doesn't contain any OCs to export.",
                    discord.Color.orange(),
                )
            )
            return

        # Export one OC.
        if oc_name:
            key = normalize_name(oc_name)
            oc = ocs.get(key)

            if oc is None:
                await ctx.send(
                    embed=make_embed(
                        "❌ OC Not Found",
                        f"I couldn't find **{oc_name}** in your OC Book.",
                        discord.Color.red(),
                    )
                )
                return

            payload = _export_payload({key: oc})
            filename = (
                f"{_safe_filename(oc.get('name', 'OC'))}_oc.json"
            )
            count_text = f"**{oc['name']}**"

        # Export entire OC list.
        else:
            payload = _export_payload(ocs)
            filename = (
                f"{_safe_filename(ctx.author.display_name)}_oc_list.json"
            )
            count_text = (
                f"**{len(ocs)}** OC"
                f"{'s' if len(ocs) != 1 else ''}"
            )

        try:
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            await ctx.send(
                embed=make_embed(
                    "❌ Export Failed",
                    f"Could not convert the OC data to JSON.\n`{error}`",
                    discord.Color.red(),
                )
            )
            return

        discord_file = discord.File(
            io.BytesIO(raw),
            filename=filename,
        )

        await ctx.send(
            embed=make_embed(
                "📦 OC JSON Exported",
                (
                    f"Exported {count_text}.\n\n"
                    f"**File:** `{filename}`\n\n"
                    "The export contains OC data, including custom "
                    "fields and custom layout data."
                ),
                discord.Color.green(),
            ),
            file=discord_file,
        )

    # ========================================================
    # 📥 IMPORT
    # ========================================================

    @bot.command(
        name="ocimport",
        aliases=["ocimportjson", "ocjsonimport"],
        help="Import an attached Archiverist OC JSON file.",
    )
    async def ocimport(ctx):
        if not ctx.message.attachments:
            await ctx.send(
                embed=make_embed(
                    "📥 OC Import",
                    (
                        "Attach an `.json` file to the same message.\n\n"
                        f"Example:\n`{ctx.prefix}ocimport` + attach JSON"
                    ),
                    discord.Color.orange(),
                )
            )
            return

        attachment = next(
            (
                item
                for item in ctx.message.attachments
                if item.filename.lower().endswith(".json")
            ),
            None,
        )

        if attachment is None:
            await ctx.send(
                embed=make_embed(
                    "❌ JSON File Required",
                    "Please attach a file ending in `.json`.",
                    discord.Color.red(),
                )
            )
            return

        if attachment.size > MAX_IMPORT_BYTES:
            await ctx.send(
                embed=make_embed(
                    "❌ File Too Large",
                    (
                        f"Maximum JSON size is "
                        f"**{MAX_IMPORT_BYTES // (1024 * 1024)} MB**."
                    ),
                    discord.Color.red(),
                )
            )
            return

        try:
            raw = await attachment.read()
            text = raw.decode("utf-8-sig")
            payload = json.loads(text)
            imported = _validate_payload(payload)

        except UnicodeDecodeError:
            await ctx.send(
                embed=make_embed(
                    "❌ Invalid Encoding",
                    "The JSON file must use UTF-8 encoding.",
                    discord.Color.red(),
                )
            )
            return

        except json.JSONDecodeError as error:
            await ctx.send(
                embed=make_embed(
                    "❌ Invalid JSON",
                    (
                        "The file isn't valid JSON.\n\n"
                        f"Line: **{error.lineno}**\n"
                        f"Column: **{error.colno}**"
                    ),
                    discord.Color.red(),
                )
            )
            return

        except ValueError as error:
            await ctx.send(
                embed=make_embed(
                    "❌ Invalid OC List",
                    str(error),
                    discord.Color.red(),
                )
            )
            return

        except discord.HTTPException:
            await ctx.send(
                embed=make_embed(
                    "❌ Download Failed",
                    "Discord could not provide the attached file.",
                    discord.Color.red(),
                )
            )
            return

        if not imported:
            await ctx.send(
                embed=make_embed(
                    "📥 Empty OC List",
                    "The JSON file contains no OCs.",
                    discord.Color.orange(),
                )
            )
            return

        book = get_book(ctx.author.id)

        imported_names = []
        skipped_names = []
        inserted_keys = []

        # Never modify the book until every imported OC has been validated.
        for original_key, oc in imported.items():
            name = str(oc.get("name", original_key)).strip()
            key = normalize_name(name)

            if not key:
                skipped_names.append(name or original_key)
                continue

            if key in book["ocs"]:
                skipped_names.append(name)
                continue

            book["ocs"][key] = deepcopy(oc)
            inserted_keys.append(key)
            imported_names.append(name)

        if not imported_names:
            await ctx.send(
                embed=make_embed(
                    "📥 Nothing Imported",
                    (
                        "None of the OCs were imported.\n\n"
                        "Existing OCs were left untouched."
                    ),
                    discord.Color.orange(),
                )
            )
            return

        try:
            await save_data()
        except Exception as error:
            # Roll back only the entries created by this import.
            for key in inserted_keys:
                book["ocs"].pop(key, None)

            await ctx.send(
                embed=make_embed(
                    "❌ Import Failed",
                    (
                        "The imported OCs could not be saved, so "
                        "the changes were rolled back.\n\n"
                        f"`{error}`"
                    ),
                    discord.Color.red(),
                )
            )
            return

        description = (
            f"✅ **Imported:** {len(imported_names)}\n"
            f"⏭️ **Skipped:** {len(skipped_names)}"
        )

        if skipped_names:
            preview = ", ".join(
                f"`{name}`"
                for name in skipped_names[:10]
            )

            if len(skipped_names) > 10:
                preview += (
                    f" + {len(skipped_names) - 10} more"
                )

            description += f"\n\n**Skipped:**\n{preview}"

        description += (
            "\n\nExisting OCs were not overwritten."
        )

        await ctx.send(
            embed=make_embed(
                "📥 OC List Imported",
                description,
                discord.Color.green(),
            )
        )

    # ========================================================
    # 📚 JSON HELP
    # ========================================================

    @bot.command(
        name="ocjson",
        aliases=["ocdata"],
        help="Show the OC JSON import/export guide.",
    )
    async def ocjson(ctx):
        await ctx.send(
            embed=make_embed(
                "📦 OC JSON Tools",
                (
                    "**📤 Export all OCs**\n"
                    f"`{ctx.prefix}ocexport`\n\n"
                    "**📤 Export one OC**\n"
                    f"`{ctx.prefix}ocexport Nova`\n\n"
                    "**📥 Import OCs**\n"
                    f"`{ctx.prefix}ocimport` + attach `.json`\n\n"
                    "**📚 JSON Help**\n"
                    f"`{ctx.prefix}ocjson`\n\n"
                    "Custom OC fields and custom layouts are preserved.\n"
                    "Profile, proxy, and personal-room settings are not exported.\n"
                    "Existing OC names are never overwritten."
                ),
                discord.Color.blurple(),
            )
        )