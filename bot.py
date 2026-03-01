import discord
from discord.ext import commands, tasks
import json, math, time, os, asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Activer "Server Members Intent" dans le Dev Portal

bot = commands.Bot(command_prefix="!", intents=intents)

XP_FILE = "xp.json"
LEADERBOARD_MESSAGE_FILE = "leaderboard_message.json"
INVITES_FILE = "invites_cache.json"
JOINED_FILE = "joined_users.json"

# ✅ x2 plus rapide
XP_PER_MESSAGE = 30
COOLDOWN = 10

TOP_LIMIT = 20
LEADERBOARD_CHANNEL_ID = 1472175781495967861

INVITE_BONUS_XP = 100

leaderboard_lock = asyncio.Lock()

# -------------------- JSON HELPERS --------------------

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

# -------------------- XP / LEVEL --------------------

def ensure_user(guild_id: str, user_id: str):
    xp_data.setdefault(guild_id, {})
    xp_data[guild_id].setdefault(user_id, {"xp": 0, "level": 0, "last_xp": 0})

# ✅ Niveau x2 plus rapide: level = sqrt(xp / 25)
def get_level(xp: int) -> int:
    return int(math.sqrt(max(0, xp) / 25))

def xp_for_level(level: int) -> int:
    return (level ** 2) * 25

def mark_joined_once(guild_id: str, user_id: str) -> bool:
    joined_users.setdefault(guild_id, {})
    if user_id in joined_users[guild_id]:
        return False
    joined_users[guild_id][user_id] = True
    save_joined()
    return True

# 🌙 Emojis lunes : 1 emoji tous les 5 niveaux
def get_rank_emoji(level: int) -> str:
    if level < 5:
        return "🌑"
    elif level < 10:
        return "🌒"
    elif level < 15:
        return "🌓"
    elif level < 20:
        return "🌔"
    elif level < 25:
        return "🌕"
    elif level < 30:
        return "🌖"
    elif level < 35:
        return "🌗"
    elif level < 40:
        return "🌘"
    elif level < 45:
        return "✨"
    else:
        return "🌌"

# -------------------- INVITES --------------------

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

# -------------------- LEADERBOARD --------------------

async def refresh_leaderboard_once():
    async with leaderboard_lock:
        for guild in bot.guilds:
            guild_id = str(guild.id)

            channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
            if channel is None:
                print(f"[LB] Salon introuvable par ID dans {guild.name} (pas d'accès ou mauvais ID).")
                continue

            me = guild.get_member(bot.user.id)
            perms = channel.permissions_for(me)
            if not perms.view_channel or not perms.send_messages:
                print(f"[LB] Permissions insuffisantes dans {guild.name}.")
                continue
            if not perms.embed_links:
                print(f"[LB] Permission 'Embed Links' manquante sur {guild.name} (le tableau peut ne pas s'afficher).")

            xp_data.setdefault(guild_id, {})

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
                badge = get_rank_emoji(level)

                xp_current_level = xp_for_level(level)
                xp_next_level = xp_for_level(level + 1)
                xp_progress = max(0, xp - xp_current_level)
                xp_needed = max(1, xp_next_level - xp_current_level)
                percent = min(100, int((xp_progress / xp_needed) * 100))

                description += (
                    f"**{rank}.** {badge} **{member.name}** — **Niv {level}**\n"
                    f"└ 🧪 {xp_progress}/{xp_needed} XP (**{percent}%**)\n"
                )

            embed = discord.Embed(
                title="🌙 Classement XP — Top 20",
                description=description or "✨ Pas encore de données.",
                color=discord.Color.from_rgb(130, 160, 255)
            )
            embed.set_footer(text="Mise à jour automatique toutes les 60 secondes ⏱️")

            msg_id = leaderboard_messages.get(guild_id)
            if msg_id:
                try:
                    msg = await channel.fetch_message(int(msg_id))
                    await msg.edit(embed=embed)
                    continue
                except Exception as e:
                    print(f"[LB] Impossible d'éditer l'ancien message (recréation). Raison: {type(e).__name__}")

            msg = await channel.send(embed=embed)
            leaderboard_messages[guild_id] = str(msg.id)
            save_leaderboard_messages()

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")

    for guild in bot.guilds:
        await rebuild_invite_cache(guild)

    await refresh_leaderboard_once()

    if not update_leaderboard.is_running():
        update_leaderboard.start()
        print("[LB] Loop leaderboard démarrée")

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

    invite_cache[guild_id] = {inv.code: (inv.uses or 0) for inv in new_invites}
    save_invites()

    if not used or not used.inviter or used.inviter.bot:
        return

    inviter_id = str(used.inviter.id)
    ensure_user(guild_id, inviter_id)

    xp_data[guild_id][inviter_id]["xp"] += INVITE_BONUS_XP

    old_level = int(xp_data[guild_id][inviter_id].get("level", 0))
    new_level = get_level(int(xp_data[guild_id][inviter_id]["xp"]))

    if new_level > old_level:
        xp_data[guild_id][inviter_id]["level"] = new_level

        # ✅ annonce level up via invite dans le salon leaderboard
        lb_channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if lb_channel:
            try:
                badge = get_rank_emoji(new_level)
                await lb_channel.send(
                    f"🎉 {badge} <@{inviter_id}> passe **niveau {new_level}** grâce à une invite !"
                )
            except discord.Forbidden:
                pass

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

    old_level = int(xp_data[guild_id][user_id].get("level", 0))
    new_level = get_level(int(xp_data[guild_id][user_id]["xp"]))

    if new_level > old_level:
        xp_data[guild_id][user_id]["level"] = new_level

        # ✅ annonce level up dans le salon où la personne parle
        try:
            badge = get_rank_emoji(new_level)
            await message.channel.send(
                f"🎉 {badge} {message.author.mention} passe **niveau {new_level}** !"
            )
        except discord.Forbidden:
            pass

    save_xp()

    await bot.process_commands(message)

# -------------------- LOOP --------------------

@tasks.loop(seconds=60)
async def update_leaderboard():
    await refresh_leaderboard_once()

# -------------------- RUN --------------------

bot.run(os.environ["TOKEN"])