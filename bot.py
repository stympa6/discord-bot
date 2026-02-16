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

# 🆕 fichiers de persistance pour les invites
INVITES_FILE = "invites_cache.json"
JOINED_FILE = "joined_users.json"

XP_PER_MESSAGE = 10
COOLDOWN = 15
TOP_LIMIT = 20
LEADERBOARD_CHANNEL_NAME = "🏆ヽleaderboard"

INVITE_XP_BONUS = 100  # 🆕 bonus XP par invite

# -------------------- UTILITAIRES FICHIERS --------------------

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# -------------------- XP / LEADERBOARD FILES --------------------

def load_xp():
    return load_json(XP_FILE, {})

def save_xp(data):
    save_json(XP_FILE, data)

def load_leaderboard_messages():
    return load_json(LEADERBOARD_MESSAGE_FILE, {})

def save_leaderboard_messages(data):
    save_json(LEADERBOARD_MESSAGE_FILE, data)

xp_data = load_xp()
leaderboard_messages = load_leaderboard_messages()

# -------------------- INVITES PERSISTANCE --------------------

# invite_cache format:
# { "<guild_id>": { "<invite_code>": <uses_int> , ... }, ... }
invite_cache = load_json(INVITES_FILE, {})

# joined_users format:
# { "<guild_id>": { "<user_id>": true, ... }, ... }
joined_users = load_json(JOINED_FILE, {})

def mark_joined_once(guild_id: str, user_id: str) -> bool:
    """Retourne True si c'est la première fois qu'on voit ce user (serveur), sinon False."""
    if guild_id not in joined_users:
        joined_users[guild_id] = {}
    if user_id in joined_users[guild_id]:
        return False
    joined_users[guild_id][user_id] = True
    save_json(JOINED_FILE, joined_users)
    return True

def set_invite_cache_for_guild(guild_id: str, invites: list[discord.Invite]):
    if guild_id not in invite_cache:
        invite_cache[guild_id] = {}
    invite_cache[guild_id] = {inv.code: (inv.uses or 0) for inv in invites}
    save_json(INVITES_FILE, invite_cache)

# -------------------- LEVEL / ICONS --------------------

def get_level(xp):
    return int(math.sqrt(xp // 10))

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

# -------------------- LEADERBOARD --------------------

async def refresh_leaderboard_once():
    for guild in bot.guilds:
        guild_id = str(guild.id)

        channel = discord.utils.get(
            guild.text_channels,
            name=LEADERBOARD_CHANNEL_NAME
        )

        if not channel or guild_id not in xp_data:
            continue

        # suppression des doublons (messages du bot avec embed)
        async for msg in channel.history(limit=20):
            if msg.author == bot.user and msg.embeds:
                if msg.id != leaderboard_messages.get(guild_id):
                    try:
                        await msg.delete()
                    except:
                        pass

        sorted_users = sorted(
            xp_data[guild_id].items(),
            key=lambda x: x[1]["xp"],
            reverse=True
        )[:TOP_LIMIT]

        description = ""

        for i, (user_id, data) in enumerate(sorted_users, start=1):
            member = guild.get_member(int(user_id))
            if not member:
                continue

            level = data["level"]
            xp = data["xp"]
            icon = get_icon(level)

            xp_current_level = (level ** 2) * 10
            xp_next_level = ((level + 1) ** 2) * 10
            xp_progress = xp - xp_current_level
            xp_needed = xp_next_level - xp_current_level
            percent = int((xp_progress / xp_needed) * 100) if xp_needed > 0 else 100

            description += (
                f"**{i}.** {icon} {member.name} "
                f"— Nv {level} | {xp_progress} / {xp_needed} XP ({percent}%)\n"
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
                return
            except:
                pass

        msg = await channel.send(embed=embed)
        leaderboard_messages[guild_id] = msg.id
        save_leaderboard_messages(leaderboard_messages)

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")

    # 🆕 initialise / refresh le cache d'invites (persistant)
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            set_invite_cache_for_guild(str(guild.id), invites)
        except discord.Forbidden:
            print(f"[INVITES] Permission manquante sur {guild.name} (Manage Server requis)")
        except Exception as e:
            print(f"[INVITES] Erreur sur {guild.name}: {e}")

    await refresh_leaderboard_once()
    if not update_leaderboard.is_running():
        update_leaderboard.start()

@bot.event
async def on_invite_create(invite: discord.Invite):
    # 🆕 met à jour le cache quand une invite est créée
    guild_id = str(invite.guild.id)
    invite_cache.setdefault(guild_id, {})
    invite_cache[guild_id][invite.code] = invite.uses or 0
    save_json(INVITES_FILE, invite_cache)

@bot.event
async def on_invite_delete(invite: discord.Invite):
    # 🆕 met à jour le cache quand une invite est supprimée
    guild_id = str(invite.guild.id)
    if guild_id in invite_cache and invite.code in invite_cache[guild_id]:
        del invite_cache[guild_id][invite.code]
        save_json(INVITES_FILE, invite_cache)

@bot.event
async def on_member_join(member: discord.Member):
    # 🆕 bonus XP à l'inviteur, 1 seule fois par membre (anti quit/join)
    guild = member.guild
    guild_id = str(guild.id)
    user_id = str(member.id)

    # anti-abus: si ce membre a déjà été compté -> rien
    if not mark_joined_once(guild_id, user_id):
        return

    try:
        new_invites = await guild.invites()
    except discord.Forbidden:
        print(f"[INVITES] Permission manquante (Manage Server) sur {guild.name}")
        return
    except Exception as e:
        print(f"[INVITES] Erreur lecture invites sur {guild.name}: {e}")
        return

    old = invite_cache.get(guild_id, {})
    used_invite = None

    # on cherche l'invite dont uses a augmenté
    for inv in new_invites:
        before_uses = old.get(inv.code, 0)
        now_uses = inv.uses or 0
        if now_uses > before_uses:
            used_invite = inv
            break

    # met à jour le cache (persistant)
    set_invite_cache_for_guild(guild_id, new_invites)

    if not used_invite or not used_invite.inviter or used_invite.inviter.bot:
        return

    inviter = used_invite.inviter
    inviter_id = str(inviter.id)

    xp_data.setdefault(guild_id, {})
    xp_data[guild_id].setdefault(inviter_id, {
        "xp": 0,
        "level": 0,
        "last_xp": 0
    })

    xp_data[guild_id][inviter_id]["xp"] += INVITE_XP_BONUS

    new_level = get_level(xp_data[guild_id][inviter_id]["xp"])
    if new_level > xp_data[guild_id][inviter_id]["level"]:
        xp_data[guild_id][inviter_id]["level"] = new_level

    save_xp(xp_data)

    try:
        await refresh_leaderboard_once()
    except:
        pass

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    now = time.time()

    xp_data.setdefault(guild_id, {})
    xp_data[guild_id].setdefault(user_id, {
        "xp": 0,
        "level": 0,
        "last_xp": 0
    })

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
    await refresh_leaderboard_once()
    await bot.process_commands(message)

# -------------------- COMMANDES --------------------

@bot.command()
async def rankxp(ctx):
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)

    if guild_id not in xp_data or user_id not in xp_data[guild_id]:
        await ctx.send("Tu n'as encore aucun XP 😅")
        return

    data = xp_data[guild_id][user_id]
    level = data["level"]
    xp = data["xp"]
    icon = get_icon(level)

    xp_current_level = (level ** 2) * 10
    xp_next_level = ((level + 1) ** 2) * 10
    xp_progress = xp - xp_current_level
    xp_needed = xp_next_level - xp_current_level
    percent = int((xp_progress / xp_needed) * 100) if xp_needed > 0 else 100

    await ctx.send(
        f"📊 **{ctx.author.name}**\n"
        f"{icon} Niveau : **{level}**\n"
        f"⭐ XP : **{xp_progress} / {xp_needed}** ({percent}%)\n"
        f"🔜 Prochain niveau à **{xp_next_level} XP total**"
    )

# -------------------- LOOP --------------------

@tasks.loop(seconds=60)
async def update_leaderboard():
    await refresh_leaderboard_once()

# -------------------- RUN --------------------

bot.run(os.environ["TOKEN"])
