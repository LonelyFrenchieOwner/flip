import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv
from flask import Flask
import logging
import random
import threading

# -------------------------------------------------------------------
# ENV + LOGGING + DISCORD BOT
# -------------------------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.DEBUG)

GUILD_ID = 1333567666983538718  # <-- CHANGE to your server's ID
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------------------------------------------
# FLASK APP FOR HEALTH CHECK
# -------------------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

# -------------------------------------------------------------------
# NEU GITHUB ENDPOINTS
# -------------------------------------------------------------------
NEU_ITEMS_LISTING_URL = (
    "https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/contents/items"
)
NEU_ITEM_RAW_URL = (
    "https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/"
    "master/items/{}.json"
)

# -------------------------------------------------------------------
# HYPIXEL ENDPOINTS (for npcflip)
# -------------------------------------------------------------------
BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"

# -------------------------------------------------------------------
# HELPER FUNCTION: fetch_json
# -------------------------------------------------------------------
async def fetch_json(url: str):
    """Fetch JSON data from a URL using content_type=None to bypass MIME issues."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logging.error(f"Error fetching {url} (status={response.status})")
                return None
            return await response.json(content_type=None)

# -------------------------------------------------------------------
# BOT EVENTS
# -------------------------------------------------------------------
@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user}")
    try:
        guild = discord.Object(id=GUILD_ID)
        # Clear all old commands for this guild
        bot.tree.clear_commands(guild=guild)

        # Register both commands
        bot.tree.add_command(npcflip)
        bot.tree.add_command(craftflip)

        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
        logging.debug(f"Registered commands: {[cmd.name for cmd in bot.tree.get_commands(guild=guild)]}")
    except Exception as e:
        logging.error(f"⚠️ Sync error: {e}")

# -------------------------------------------------------------------
# SLASH COMMAND: /npcflip
# -------------------------------------------------------------------
@bot.tree.command(
    name="npcflip",
    description="Shows the top 15 NPC flips based on buy order and instant buy",
    guild=discord.Object(id=GUILD_ID)
)
async def npcflip(interaction: discord.Interaction):
    """Your original /npcflip command for top 15 flips."""
    await interaction.response.defer()

    bazaar_data = await fetch_json(BAZAAR_API_URL)
    items_data = await fetch_json(ITEMS_API_URL)
    if not bazaar_data or "products" not in bazaar_data:
        return await interaction.followup.send("Failed to fetch Bazaar data.")
    if not items_data or "items" not in items_data:
        return await interaction.followup.send("Failed to fetch Items data.")

    # Build NPC price map
    npc_prices = {
        item["id"]: item["npc_sell_price"]
        for item in items_data["items"]
        if "npc_sell_price" in item
    }

    flips = []
    for item_id, data in bazaar_data["products"].items():
        if item_id in npc_prices:
            npc_sell_price = npc_prices[item_id]
            insta_buy_price = data["quick_status"].get("buyPrice", 0)
            buy_order_price = data["quick_status"].get("sellPrice", 0)

            if insta_buy_price > 0:
                profit = npc_sell_price - insta_buy_price
                flips.append((item_id, profit, "insta", insta_buy_price))
            if buy_order_price > 0:
                profit = npc_sell_price - buy_order_price
                flips.append((item_id, profit, "buyorder", buy_order_price))

    # Sort & pick top 15 for insta and buy order
    insta_flips = sorted([f for f in flips if f[2] == "insta"], key=lambda x: x[1], reverse=True)[:15]
    buy_order_flips = sorted([f for f in flips if f[2] == "buyorder"], key=lambda x: x[1], reverse=True)[:15]

    description = "**BUY ORDER**                 |            **INSTA BUY**\n"
    description += "--------------------------------------------------------------\n\n"

    # Display side-by-side
    for bo, ib in zip(buy_order_flips, insta_flips):
        bo_name = bo[0].replace("_", " ").title()
        ib_name = ib[0].replace("_", " ").title()
        bo_profit = f"**{bo[1]:,.0f}** coins profit"
        ib_profit = f"**{ib[1]:,.0f}** coins profit"
        description += f"{bo_name:<25} ({bo_profit})  **|**  {ib_name:<25} ({ib_profit})\n\n"

    embed = discord.Embed(
        title="💰 Top 15 NPC Flips",
        description=description,
        color=discord.Color.gold()
    )
    embed.set_footer(text="Hypixel Skyblock Bazaar Flipping Bot")
    await interaction.followup.send(embed=embed)

# -------------------------------------------------------------------
# SLASH COMMAND: /craftflip
# -------------------------------------------------------------------
@bot.tree.command(
    name="craftflip",
    description="Grab a random recipe from the NEU repo and display it",
    guild=discord.Object(id=GUILD_ID)
)
async def craftflip(interaction: discord.Interaction):
    """Picks one random .json file from the NEU repo and shows its 'recipe' or 'crafting' data."""
    await interaction.response.defer()

    # 1) Fetch the directory listing of NEU items
    files = await fetch_json(NEU_ITEMS_LISTING_URL)
    if not files or not isinstance(files, list):
        return await interaction.followup.send("Failed to fetch NEU items listing.")

    # 2) Pick a random .json file
    random_file = random.choice(files)
    item_id = random_file["name"].replace(".json", "")

    # 3) Fetch the item data
    item_url = NEU_ITEM_RAW_URL.format(item_id)
    item_data = await fetch_json(item_url)
    if not item_data:
        return await interaction.followup.send(f"Failed to fetch item data for `{item_id}`.")

    # 4) Some NEU items store recipes under "crafting" -> "materials"
    #    Others store them under "recipe" -> {A1...C3}
    crafting_info = item_data.get("crafting", {})
    recipe_info = item_data.get("recipe", {})

    # If "crafting" is present, check for "materials"
    if crafting_info:
        materials = crafting_info.get("materials", [])
        if materials:
            desc = f"**Random Item:** `{item_id}`\n\n**Crafting Materials**:\n"
            for mat in materials:
                mat_name = mat["id"]
                mat_count = mat["count"]
                desc += f"- {mat_count}x {mat_name}\n"
        else:
            desc = f"**{item_id}** has 'crafting' but no 'materials' array."
    elif recipe_info:
        # We have a 3x3 "recipe" object (A1, B2, etc.)
        desc = f"**Random Item:** `{item_id}`\n\n**3×3 Recipe**:\n"
        for row_label in ["A", "B", "C"]:
            row_str = ""
            for col_num in ["1", "2", "3"]:
                slot = row_label + col_num
                slot_val = recipe_info.get(slot, "Empty")
                row_str += f"[{slot_val}] "
            desc += f"{row_label} row: {row_str}\n"
    else:
        desc = f"**{item_id}** doesn't have a 'crafting' or 'recipe' section."

    embed = discord.Embed(
        title=f"Random Recipe: {item_id}",
        description=desc,
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed)

# -------------------------------------------------------------------
# RUN THE BOT & FLASK HEALTH CHECK
# -------------------------------------------------------------------
def run_flask():
    app.run(host="0.0.0.0", port=8000)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(BOT_TOKEN)
