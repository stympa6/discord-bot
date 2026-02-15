import discord
from discord.ext import commands, tasks
import json
import math
import time
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # IMPORTANT: activer "Server Members Intent" dans le Dev Portal

bot = commands.Bot(command_prefix="!", intents=intents)

XP_FILE = "xp.json"
LEADERBOARD_MESSAGE_FILE = "leaderboard_message.json"

XP_PER_MESSAGE = 10
COOLDOWN = 15
TOP_LIMIT = 20
LEADERBOARD_CHANNEL_NAME = "🏆ヽleaderboard"

INVITE_BONUS_XP = 100

# CACHE INVITATIONS
invite_cache = {}  # guild_id -> list[Invite]


# -------------------- UTILITAIRES --------------------

def load_xp():
    if not os.path.exists(XP_FILE):
        return {}
    with open(XP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_xp(data):
    with open(XP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_leaderboard_messages():
    if not os.path.exists(LEADERBOARD_MESSAGE_FILE):
        return {}
    with open(LEADERBOARD_MESSAGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_leaderboard_messages(data):
    with open(LEADERBOARD_MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

xp_data = load_xp()
leaderboard_messages = load_leaderboard_messages()

def get_level(xp: int) -> int:
    return int(math.sqrt(xp // 10))

def ensure_user(guild_id: str, user_id: str):
    xp_data.setdefault(guild_id, {})
    xp_data[guild_id].setdefault(user_id, {
        "xp": 0,
        "level": 0,
        "last_xp": 0
    })


# -------------------- COULEURS --------------------

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


# -------------------- INVITES HELPERS --------------------

async def rebuild_invite_cache(guild: discord.Guild):
    """Recharge toutes les invites du serveur dans le cache."""
    try:
        invite_cache[guild.id] = await guild.invites()
    except discord.Forbidden:
        invite_cache[guild.id] = []
        print(f"[INVITES] Permission refusée sur {guild.name} -> donne 'Gérer le serveur' au bot.")
    except Exception as e:
        invite_cache[guild.id] = []
        print(f"[INVITES] Erreur cache {guild.name}: {e}")

def find_inviter(old_invites, new_invites):
    """Détecte l'invite dont uses a augmenté."""
    old_uses = {inv.code: (inv.uses or 0) for inv in old_invites}
    for inv in new_invites:
        before = old_uses.get(inv.code, 0)
        now = inv.uses or 0
        if now > before:
            return inv.inviter
    return None


# -------------------- LEADERBOARD --------------------

async def refresh_leaderboard_once():
    for guild in bot.guilds:
        guild_id = str(guild.id)

        channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        if not channel or guild_id not in xp_data:
            continue

        # Nettoyage des anciens embeds du bot (si plusieurs)
        try:
            async for msg in channel.history(limit=25):
                if msg.author == bot.user and msg.embeds:
                    if msg.id != leaderboard_messages.get(guild_id):
                        try:
                            await msg.delete()
                        except:
                            pass
        except:
            pass

        sorted_users = sorted(
            xp_data[guild_id].items(),
            key=lambda x: x[1].get("xp", 0),
            reverse=True
        )[:TOP_LIMIT]

        description = ""
        rank = 0

        for user_id, data in sorted_users:
            member = guild.get_member(int(user_id))
            if not member:
                continue

            rank += 1
            level = data.get("level", 0)
            xp = data.get("xp", 0)
            icon = get_icon(level)

            xp_current_level = (level ** 2) * 10
            xp_next_level = ((level + 1) ** 2) * 10
            xp_progress = xp - xp_current_level
            xp_needed = xp_next_level - xp_current_level
            percent = int((xp_progress / xp_needed) * 100) if xp_needed > 0 else 100

            description += (
                f"**{rank}.** {icon} {member.name} — Nv {level} | "
                f"{xp_progress} / {xp_needed} XP ({percent}%)\n"
            )

        embed = discord.Embed(
            title="🏆 Leaderboard — Top 20",
            description=description or "Pas encore de données.",
            color=discord.Color.red()
        )

        # ⚠️ BUGFIX: ne PAS return ici (sinon ça update un seul serveur)
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


# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")

    # Cache des invitations au démarrage
    for guild in bot.guilds:
        await rebuild_invite_cache(guild)

    await refresh_leaderboard_once()
    if not update_leaderboard.is_running():
        update_leaderboard.start()

@bot.event
async def on_guild_join(guild):
    await rebuild_invite_cache(guild)

@bot.event
async def on_invite_create(invite):
    await rebuild_invite_cache(invite.guild)

@bot.event
async def on_invite_delete(invite):
    await rebuild_invite_cache(invite.guild)

@bot.event
async def on_member_join(member):
    guild = member.guild

    # Récupère nouvelles invites
    try:
        new_invites = await guild.invites()
    except discord.Forbidden:
        print(f"[INVITES] Forbidden sur {guild.name} -> donne 'Gérer le serveur' au bot.")
        return
    except Exception as e:
        print(f"[INVITES] Erreur guild.invites() sur {guild.name}: {e}")
        return

    old_invites = invite_cache.get(guild.id, [])
    inviter = find_inviter(old_invites, new_invites)

    # Met à jour le cache
    invite_cache[guild.id] = new_invites

    if not inviter or inviter.bot:
        # Cela arrive si vanity/discovery ou si invite non traçable
        return

    guild_id = str(guild.id)
    inviter_id = str(inviter.id)

    ensure_user(guild_id, inviter_id)

    xp_data[guild_id][inviter_id]["xp"] += INVITE_BONUS_XP
    new_level = get_level(xp_data[guild_id][inviter_id]["xp"])
    if new_level > xp_data[guild_id][inviter_id]["level"]:
        xp_data[guild_id][inviter_id]["level"] = new_level

    save_xp(xp_data)

    # Update leaderboard maintenant (utile car c'est un "event important")
    await refresh_leaderboard_once()

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    now = time.time()

    ensure_user(guild_id, user_id)

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

    # IMPORTANT: on ne refresh plus à chaque message (évite rate-limit).
    # Le leaderboard est mis à jour par la loop toutes les 60s.
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
