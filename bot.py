import discord
from discord.ext import commands, tasks
import json
import math
import time
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

XP_FILE = "xp.json"
LEADERBOARD_MESSAGE_FILE = "leaderboard_message.json"

XP_PER_MESSAGE = 10
COOLDOWN = 15
TOP_LIMIT = 20
LEADERBOARD_CHANNEL_NAME = "🏆ヽleaderboard"

# -------------------- UTILITAIRES --------------------

def load_xp():
    if not os.path.exists(XP_FILE):
        return {}
    with open(XP_FILE, "r") as f:
        return json.load(f)

def save_xp(data):
    with open(XP_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_leaderboard_messages():
    if not os.path.exists(LEADERBOARD_MESSAGE_FILE):
        return {}
    with open(LEADERBOARD_MESSAGE_FILE, "r") as f:
        return json.load(f)

def save_leaderboard_messages(data):
    with open(LEADERBOARD_MESSAGE_FILE, "w") as f:
        json.dump(data, f, indent=4)

xp_data = load_xp()
leaderboard_messages = load_leaderboard_messages()

def get_level(xp):
    return int(math.sqrt(xp // 10))

# -------------------- COULEURS DE NIVEAU --------------------

def get_icon(level):
    if level < 5:
        return "🟢"
    elif level < 10:
        return "🟡"
    elif level < 15:
        return "🟠"
    elif level < 20:
        return "🔴"
    elif level < 30:
        return "🟥"
    else:
        return "💀"

# -------------------- BARRE DE PROGRESSION --------------------

def get_xp_bar(xp, level, length=10):
    current_level_xp = (level ** 2) * 10
    next_level_xp = ((level + 1) ** 2) * 10

    progress = xp - current_level_xp
    total = next_level_xp - current_level_xp

    if total <= 0:
        return "██████████ 100%"

    ratio = progress / total
    filled = int(ratio * length)
    empty = length - filled
    percent = int(ratio * 100)

    return f"{'█' * filled}{'░' * empty} {percent}%"

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")
    if not update_leaderboard.is_running():
        update_leaderboard.start()

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    now = time.time()

    if guild_id not in xp_data:
        xp_data[guild_id] = {}

    if user_id not in xp_data[guild_id]:
        xp_data[guild_id][user_id] = {
            "xp": 0,
            "level": 0,
            "last_xp": 0
        }

    if now - xp_data[guild_id][user_id]["last_xp"] < COOLDOWN:
        await bot.process_commands(message)
        return

    xp_data[guild_id][user_id]["xp"] += XP_PER_MESSAGE
    xp_data[guild_id][user_id]["last_xp"] = now

    new_level = get_level(xp_data[guild_id][user_id]["xp"])

    if new_level > xp_data[guild_id][user_id]["level"]:
        xp_data[guild_id][user_id]["level"] = new_level
        icon = get_icon(new_level)
        await message.channel.send(
            f"🎉 {icon} {message.author.mention} passe niveau **{new_level}** !"
        )

    save_xp(xp_data)

    # ⚡ UPDATE LEADERBOARD INSTANTANÉ (AJOUT UNIQUEMENT)
    if update_leaderboard.is_running():
        await update_leaderboard()

    await bot.process_commands(message)

# -------------------- COMMANDES --------------------

@bot.command()
async def rank(ctx):
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)

    if guild_id not in xp_data or user_id not in xp_data[guild_id]:
        await ctx.send("Tu n'as encore aucun XP 😅")
        return

    data = xp_data[guild_id][user_id]
    icon = get_icon(data["level"])

    await ctx.send(
        f"📊 **{ctx.author.name}**\n"
        f"{icon} Niveau : **{data['level']}**\n"
        f"⭐ XP : **{data['xp']}**"
    )

@bot.command()
async def rankxp(ctx):
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)

    if guild_id not in xp_data or user_id not in xp_data[guild_id]:
        await ctx.send("Tu n'as encore aucun XP 😅")
        return

    data = xp_data[guild_id][user_id]
    icon = get_icon(data["level"])
    bar = get_xp_bar(data["xp"], data["level"])

    await ctx.send(
        f"📊 **{ctx.author.name}**\n"
        f"{icon} Niveau : **{data['level']}**\n"
        f"⭐ XP : **{data['xp']}**\n"
        f"`{bar}`"
    )

# -------------------- LEADERBOARD --------------------

@tasks.loop(seconds=60)
async def update_leaderboard():
    for guild in bot.guilds:

        guild_id = str(guild.id)

        channel = discord.utils.get(
            guild.text_channels,
            name=LEADERBOARD_CHANNEL_NAME
        )

        if not channel:
            continue

        if guild_id not in xp_data:
            continue

        sorted_users = sorted(
            xp_data[guild_id].items(),
            key=lambda x: x[1]["xp"],
            reverse=True
        )[:TOP_LIMIT]

        description = ""

        for i, (user_id, data) in enumerate(sorted_users, start=1):
            member = guild.get_member(int(user_id))
            if member:
                icon = get_icon(data["level"])
                bar = get_xp_bar(data["xp"], data["level"])
                description += (
                    f"**{i}.** {icon} {member.name} "
                    f"— Nv {data['level']} | {bar}\n"
                )

        embed = discord.Embed(
            title="🏆 Leaderboard — Top 20",
            description=description or "Pas encore de données.",
            color=discord.Color.red()
        )

        if guild_id in leaderboard_messages:
            try:
                msg = await channel.fetch_message(leaderboard_messages[guild_id])
                await msg.edit(embed=embed)
                continue
            except:
                pass

        msg = await channel.send(embed=embed)
        leaderboard_messages[guild_id] = msg.id
        save_leaderboard_messages(leaderboard_messages)

# -------------------- RUN --------------------

import os
bot.run(os.environ["TOKEN"])
