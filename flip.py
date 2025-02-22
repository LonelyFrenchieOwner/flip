import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv
from flask import Flask
import logging
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
# HYPIXEL & NEU CONSTANTS
# -------------------------------------------------------------------
BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
AUCTION_API_URL = "https://api.hypixel.net/skyblock/auctions"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"
NEU_ITEMS_URL = (
    "https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/"
    "master/items/{}.json"
)

# -------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------
async def fetch_json(url: str):
    """Fetch JSON data from a URL using content_type=None to bypass MIME issues."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logging.error(f"Error fetching data from {url}: {response.status}")
                    return None
                return await response.json(content_type=None)
    except Exception as e:
        logging.error(f"Error fetching data from {url}: {e}")
        return None

# Global cache for NEU items (fetched once at startup)
neu_items_cache = {}

async def fetch_neu_items():
    """Fetch NEU item data (all .json files) from GitHub once."""
    neu_data = {}
    try:
        async with aiohttp.ClientSession() as session:
            api_url = "https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/contents/items"
            async with session.get(api_url) as response:
                if response.status != 200:
                    logging.error(f"Failed to fetch NEU items list. Status code: {response.status}")
                    return neu_data
                files = await response.json(content_type=None)
                for file in files:
                    item_id = file["name"].replace(".json", "")
                    url = NEU_ITEMS_URL.format(item_id)
                    async with session.get(url) as item_response:
                        if item_response.status != 200:
                            logging.error(
                                f"Failed to fetch data for item '{item_id}' (status: {item_response.status})"
                            )
                            if item_response.status in (403, 429):
                                logging.error("Likely rate-limited by GitHub.")
                            continue
                        item_data = await item_response.json(content_type=None)
                        neu_data[item_id] = item_data
    except Exception as e:
        logging.error(f"Error fetching NEU items: {e}")
    return neu_data

# -------------------------------------------------------------------
# BOT EVENTS
# -------------------------------------------------------------------
@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user}")

    # Cache NEU items on startup
    global neu_items_cache
    neu_items_cache = await fetch_neu_items()
    logging.info(f"NEU items fetched; total count: {len(neu_items_cache)}")

    # Sync guild commands (they appear faster as guild commands)
    try:
        guild_obj = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild_obj)
        logging.info(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
        logging.debug(f"Registered commands: {[cmd.name for cmd in bot.tree.get_commands(guild=guild_obj)]}")
    except Exception as e:
        logging.error(f"⚠️ Sync error: {e}")

# -------------------------------------------------------------------
# SLASH COMMANDS (Guild-specific)
# -------------------------------------------------------------------
@bot.tree.command(
    name="npcflip",
    description="Shows the top 15 NPC flips based on buy order and instant buy",
    guild=discord.Object(id=GUILD_ID)
)
async def npc_flip(interaction: discord.Interaction):
    await interaction.response.defer()
    bazaar_data = await fetch_json(BAZAAR_API_URL)
    items_data = await fetch_json(ITEMS_API_URL)
    
    if not bazaar_data or not items_data:
        logging.error("Failed to fetch data from Hypixel API for NPC flips.")
        return await interaction.followup.send("Failed to fetch data from Hypixel API.")
    
    npc_prices = {item["id"]: item["npc_sell_price"] for item in items_data.get("items", []) if "npc_sell_price" in item}
    flips = []
    for item_id, data in bazaar_data["products"].items():
        if item_id in npc_prices:
            npc_sell_price = npc_prices[item_id]
            insta_buy_price = data["quick_status"].get("buyPrice", 0)
            buy_order_price = data["quick_status"].get("sellPrice", 0)
            if insta_buy_price > 0:
                flips.append((item_id, npc_sell_price - insta_buy_price, "insta", insta_buy_price))
            if buy_order_price > 0:
                flips.append((item_id, npc_sell_price - buy_order_price, "buyorder", buy_order_price))
    
    insta_flips = sorted([f for f in flips if f[2] == "insta"], key=lambda x: x[1], reverse=True)[:15]
    buy_order_flips = sorted([f for f in flips if f[2] == "buyorder"], key=lambda x: x[1], reverse=True)[:15]
    
    description = "**BUY ORDER**                 |            **INSTA BUY**\n"
    description += "--------------------------------------------------------------\n\n"
    for bo, ib in zip(buy_order_flips, insta_flips):
        bo_name = bo[0].replace("_", " ").title()
        ib_name = ib[0].replace("_", " ").title()
        bo_profit = f"**{bo[1]:,.0f}** coins profit"
        ib_profit = f"**{ib[1]:,.0f}** coins profit"
        description += f"{bo_name:<25} ({bo_profit})  **|**  {ib_name:<25} ({ib_profit})\n\n"
    
    embed = discord.Embed(title="💰 Top 15 NPC Flips", description=description, color=discord.Color.gold())
    embed.set_footer(text="Hypixel Skyblock Bazaar Flipping Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(
    name="craftflip",
    description="Shows the top 15 craft flips based on lowest BIN and Bazaar price",
    guild=discord.Object(id=GUILD_ID)
)
async def craft_flip(interaction: discord.Interaction):
    # Wrap defer in try/except to catch Unknown interaction errors.
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.errors.NotFound as e:
        logging.error(f"Interaction not found when deferring in craftflip: {e}")
        return

    bazaar_data = await fetch_json(BAZAAR_API_URL)
    auction_data = await fetch_json(AUCTION_API_URL)
    
    if not bazaar_data or not auction_data or not neu_items_cache:
        logging.error("Failed to fetch Bazaar, Auction, or NEU items data.")
        return await interaction.followup.send("Failed to fetch necessary data.")
    
    # Build a mapping of the lowest BIN price by item name
    lowest_bin = {}
    for auction in auction_data.get("auctions", []):
        if auction.get("bin", False):
            item_id = auction.get("item_name", "").replace(" ", "_").upper()
            price = auction["starting_bid"]
            if item_id not in lowest_bin or price < lowest_bin[item_id]:
                lowest_bin[item_id] = price
    
    flips = []
    for item_id, item_data in neu_items_cache.items():
        crafting_info = item_data.get("crafting", {})
        materials = crafting_info.get("materials", [])
        if not materials:
            continue
        craft_cost = 0
        for mat in materials:
            mat_id = mat["id"]
            mat_count = mat["count"]
            product = bazaar_data["products"].get(mat_id, {})
            quick_status = product.get("quick_status", {})
            mat_sell_price = quick_status.get("sellPrice", 0)
            if mat_sell_price <= 0:
                craft_cost = 0
                break
            craft_cost += mat_sell_price * mat_count
        if craft_cost <= 0:
            continue
        final_id = item_id.upper()
        bin_price = lowest_bin.get(final_id, float('inf'))
        bazaar_sell = bazaar_data["products"].get(final_id, {}).get("quick_status", {}).get("sellPrice", float('inf'))
        lowest_price = min(bin_price, bazaar_sell)
        if lowest_price == float('inf'):
            continue
        profit = lowest_price - craft_cost
        flips.append((item_id.replace("_", " ").title(), profit, craft_cost, lowest_price))
    
    top_flips = sorted(flips, key=lambda x: x[1], reverse=True)[:15]
    description = "**Top 15 Craft Flips**\n\n"
    for name, profit, cost, price in top_flips:
        description += f"🔹 **{name}** - **{profit:,.0f}** coins profit\n"
        description += f"   🏷️ Craft Cost: {cost:,.0f} | 🏪 Lowest Price: {price:,.0f}\n\n"
    
    embed = discord.Embed(title="💰 Top 15 Craft Flips", description=description, color=discord.Color.gold())
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
