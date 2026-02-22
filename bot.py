import discord
from discord.ext import commands, tasks
import json, math, time, os, asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # + activer "Server Members Intent" dans Dev Portal

bot = commands.Bot(command_prefix="!", intents=intents)

XP_FILE = "xp.json"
LEADERBOARD_MESSAGE_FILE = "leaderboard_message.json"
INVITES_FILE = "invites_cache.json"
JOINED_FILE = "joined_users.json"

XP_PER_MESSAGE = 10
COOLDOWN = 15
TOP_LIMIT = 20
LEADERBOARD_CHANNEL_NAME = "🏆ヽleaderboard"
INVITE_BONUS_XP = 100

leaderboard_lock = asyncio.Lock()

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

xp_data = load_json(XP_FILE, {})
leaderboard_messages = load_json(LEADERBOARD_MESSAGE_FILE, {})
invite_cache = load_json(INVITES_FILE, {})      # {guild_id: {code: uses}}
joined_users = load_json(JOINED_FILE, {})       # {guild_id: {user_id: true}}

def save_xp():
    save_json(XP_FILE, xp_data)

def save_leaderboard_messages():
    save_json(LEADERBOARD_MESSAGE_FILE, leaderboard_messages)

def save_invites():
    save_json(INVITES_FILE, invite_cache)

def save_joined():
    save_json(JOINED_FILE, joined_users)

def ensure_user(guild_id: str, user_id: str):
    xp_data.setdefault(guild_id, {})
    xp_data[guild_id].setdefault(user_id, {"xp": 0, "level": 0, "last_xp": 0})

def get_level(xp: int) -> int:
    return int(math.sqrt(xp // 10))

def mark_joined_once(guild_id: str, user_id: str) -> bool:
    joined_users.setdefault(guild_id, {})
    if user_id in joined_users[guild_id]:
        return False
    joined_users[guild_id][user_id] = True
    save_joined()
    return True

def get_icon(level: int) -> str:
    if level < 5:
        return "🌱"
    if level < 10:
        return "🔥"
    if level < 20:
        return "⚡"
    return "💀"

async def rebuild_invite_cache(guild: discord.Guild):
    """Stocke {code: uses}"""
    guild_id = str(guild.id)
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        invite_cache[guild_id] = {}
        print(f"[INVITES] Permission refusée sur {guild.name} -> donne 'Gérer le serveur' au bot.")
        save_invites()
        return
    except Exception as e:
        invite_cache[guild_id] = {}
        print(f"[INVITES] Erreur sur {guild.name}: {e}")
        save_invites()
        return

    invite_cache[guild_id] = {inv.code: (inv.uses or 0) for inv in invites}
    save_invites()

def find_used_invite(old_map: dict, new_invites: list[discord.Invite]):
    """Renvoie l'Invite dont uses a augmenté, ou None"""
    for inv in new_invites:
        before = old_map.get(inv.code, 0)
        now = inv.uses or 0
        if now > before:
            return inv
    return None

async def refresh_leaderboard_once():
    async with leaderboard_lock:
        for guild in bot.guilds:
            guild_id = str(guild.id)

            channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
            if not channel:
                continue

            if guild_id not in xp_data:
                continue

            # Tri safe
            items = list(xp_data[guild_id].items())
            items.sort(key=lambda kv: int(kv[1].get("xp", 0)), reverse=True)
            top = items[:TOP_LIMIT]

            description = ""
            rank = 0

            for user_id, data in top:
                member = guild.get_member(int(user_id))
                if not member:
                    continue
                rank += 1
                level = int(data.get("level", 0))
                xp = int(data.get("xp", 0))
                icon = get_icon(level)

                xp_current_level = (level ** 2) * 10
                xp_next_level = ((level + 1) ** 2) * 10
                xp_progress = max(0, xp - xp_current_level)
                xp_needed = max(1, xp_next_level - xp_current_level)
                percent = min(100, int((xp_progress / xp_needed) * 100))

                description += (
                    f"**{rank}.** {icon} {member.name} — Nv {level} | "
                    f"{xp_progress} / {xp_needed} XP ({percent}%)\n"
                )

            embed = discord.Embed(
                title="🏆 Leaderboard — Top 20",
                description=description or "Pas encore de données.",
                color=discord.Color.red()
            )

            # self-heal: edit si possible sinon recrée
            msg_id = leaderboard_messages.get(guild_id)
            if msg_id:
                try:
                    msg = await channel.fetch_message(int(msg_id))
                    await msg.edit(embed=embed)
                    continue
                except Exception:
                    pass

            msg = await channel.send(embed=embed)
            leaderboard_messages[guild_id] = str(msg.id)
            save_leaderboard_messages()

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")
    for guild in bot.guilds:
        await rebuild_invite_cache(guild)

    await refresh_leaderboard_once()

    if not update_leaderboard.is_running():
        update_leaderboard.start()

@bot.event
async def on_guild_join(guild):
    await rebuild_invite_cache(guild)

@bot.event
async def on_invite_create(invite: discord.Invite):
    await rebuild_invite_cache(invite.guild)

@bot.event
async def on_invite_delete(invite: discord.Invite):
    await rebuild_invite_cache(invite.guild)

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    guild_id = str(guild.id)
    user_id = str(member.id)

    # anti quit/join
    if not mark_joined_once(guild_id, user_id):
        return

    try:
        new_invites = await guild.invites()
    except discord.Forbidden:
        print(f"[INVITES] Forbidden sur {guild.name} -> donne 'Gérer le serveur' au bot.")
        return
    except Exception as e:
        print(f"[INVITES] Erreur guild.invites() sur {guild.name}: {e}")
        return

    old_map = invite_cache.get(guild_id, {})
    used = find_used_invite(old_map, new_invites)

    # update cache
    invite_cache[guild_id] = {inv.code: (inv.uses or 0) for inv in new_invites}
    save_invites()

    if not used or not used.inviter or used.inviter.bot:
        return

    inviter_id = str(used.inviter.id)
    ensure_user(guild_id, inviter_id)

    xp_data[guild_id][inviter_id]["xp"] += INVITE_BONUS_XP
    new_level = get_level(xp_data[guild_id][inviter_id]["xp"])
    if new_level > xp_data[guild_id][inviter_id]["level"]:
        xp_data[guild_id][inviter_id]["level"] = new_level

    save_xp()

@bot.event
async def on_message(message: discord.Message):
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

    save_xp()

    # IMPORTANT: pas de refresh ici (évite rate-limit)
    await bot.process_commands(message)

@tasks.loop(seconds=60)
async def update_leaderboard():
    await refresh_leaderboard_once()

bot.run(os.environ["TOKEN"])