import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv
from flask import Flask
import logging

# Initialize environment and bot
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Set up logging
logging.basicConfig(level=logging.DEBUG)  # Log all messages at DEBUG level

# Discord Bot setup
GUILD_ID = 1333567666983538718  # Replace with your actual guild ID
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Hypixel API URLs
BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
AUCTION_API_URL = "https://api.hypixel.net/skyblock/auctions"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"
NEU_ITEMS_URL = "https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/master/items/{}.json"

# Initialize Flask app for health check (optional)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

async def fetch_json(url: str):
    """Fetch JSON data from a URL with error logging."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logging.error(f"Error fetching data from {url}: {response.status}")
                    return None
                data = await response.json()
                return data
    except Exception as e:
        logging.error(f"Error fetching data from {url}: {e}")
        return None

# ------------------------------------------------
# 1) Cache NEU items once at startup
# ------------------------------------------------
neu_items_cache = {}  # global in-memory cache

async def fetch_neu_items():
    """Fetch NEU item data from GitHub dynamically (all items)."""
    neu_data = {}
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Get a list of item .json files from the NEU repo
            async with session.get("https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/contents/items") as response:
                if response.status != 200:
                    logging.error(f"Failed to fetch NEU items list. Status code: {response.status}")
                    return neu_data
                
                files = await response.json()
                
                # 2. For each .json file, fetch the actual item data
                for file in files:
                    item_id = file["name"].replace(".json", "")
                    neu_url = NEU_ITEMS_URL.format(item_id)
                    async with session.get(neu_url) as item_response:
                        if item_response.status != 200:
                            logging.error(
                                f"Failed to fetch data for item '{item_id}' "
                                f"(status: {item_response.status})"
                            )
                            # 3) Log if rate-limited
                            if item_response.status in (403, 429):
                                logging.error(f"GitHub might be rate-limiting or forbidding item: {item_id}")
                            continue
                        
                        item_data = await item_response.json()
                        neu_data[item_id] = item_data

    except Exception as e:
        logging.error(f"Error fetching NEU items: {e}")
    return neu_data

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user}")

    try:
        # Pre-fetch and cache NEU items once
        global neu_items_cache
        neu_items_cache = await fetch_neu_items()
        logging.info(f"Fetched NEU items; total items in cache: {len(neu_items_cache)}")

        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)

        # Sync commands to your guild
        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
        
        # Debugging: List all registered commands
        logging.debug(f"Registered commands: {[cmd.name for cmd in bot.tree.get_commands()]}")

    except Exception as e:
        logging.error(f"⚠️ Sync error: {e}")

# ------------------------------------------------
# Slash Commands
# ------------------------------------------------

@bot.tree.command(name="npcflip", description="Shows the top 15 NPC flips based on buy order and instant buy")
async def npc_flip(interaction: discord.Interaction):
    await interaction.response.defer()

    bazaar_data = await fetch_json(BAZAAR_API_URL)
    items_data = await fetch_json(ITEMS_API_URL)
    
    if not bazaar_data or not items_data:
        logging.error("Failed to fetch data from Hypixel API for NPC flips.")
        return await interaction.followup.send("Failed to fetch data from Hypixel API.")
    
    npc_prices = {
        item["id"]: item["npc_sell_price"]
        for item in items_data.get("items", [])
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
    
    # Separate and sort
    insta_flips = sorted([f for f in flips if f[2] == "insta"], key=lambda x: x[1], reverse=True)[:15]
    buy_order_flips = sorted([f for f in flips if f[2] == "buyorder"], key=lambda x: x[1], reverse=True)[:15]
    
    description = "**BUY ORDER**                 |            **INSTA BUY**\n"
    description += "--------------------------------------------------------------\n\n"
    
    # Zip them to display side by side
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
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="craftflip", description="Shows the top 15 craft flips based on lowest BIN and Bazaar price")
async def craft_flip(interaction: discord.Interaction):
    await interaction.response.defer()

    bazaar_data = await fetch_json(BAZAAR_API_URL)
    auction_data = await fetch_json(AUCTION_API_URL)

    if not bazaar_data or not auction_data or not neu_items_cache:
        logging.error("Failed to fetch Bazaar, Auction, or NEU items data.")
        return await interaction.followup.send("Failed to fetch necessary data.")

    # Build a map of the lowest BIN price by item name
    lowest_bin = {}
    for auction in auction_data.get("auctions", []):
        if auction.get("bin", False):
            # Example transform: "SUPERIOR_DRAGON_HELMET"
            item_id = auction.get("item_name", "").replace(" ", "_").upper()
            price = auction["starting_bid"]
            if item_id not in lowest_bin or price < lowest_bin[item_id]:
                lowest_bin[item_id] = price

    flips = []
    # Use the globally cached NEU items
    for item_id, item_data in neu_items_cache.items():
        craft_info = item_data.get("crafting", {})
        materials = craft_info.get("materials", [])
        if not materials:
            continue  # skip items with no recipe

        # Calculate total craft cost from Bazaar
        craft_cost = 0
        for mat in materials:
            mat_id = mat["id"]  # e.g. "LOG:2" or "REDSTONE"
            mat_count = mat["count"]

            product_data = bazaar_data["products"].get(mat_id, {})
            quick_status = product_data.get("quick_status", {})
            mat_sell_price = quick_status.get("sellPrice", 0)

            if mat_sell_price <= 0:
                # If any material can't be bought from Bazaar, skip
                craft_cost = 0
                break

            craft_cost += mat_sell_price * mat_count

        if craft_cost <= 0:
            continue

        # Now find the lowest "sell" price for the final crafted item
        # We'll compare the BIN auction price to the Bazaar price
        final_item_id = item_id.upper()  # e.g. "SUPERIOR_DRAGON_HELMET"
        bin_price = lowest_bin.get(final_item_id, float('inf'))
        bazaar_sell = bazaar_data["products"].get(final_item_id, {}).get("quick_status", {}).get("sellPrice", float('inf'))
        lowest_price = min(bin_price, bazaar_sell)

        if lowest_price == float('inf'):
            # Means no recognized BIN or no Bazaar product
            continue

        profit = lowest_price - craft_cost
        flips.append((item_id.replace("_", " ").title(), profit, craft_cost, lowest_price))

    # Sort by highest profit and take top 15
    top_flips = sorted(flips, key=lambda x: x[1], reverse=True)[:15]

    description = "**Top 15 Craft Flips**\n\n"
    for name, profit, cost, price in top_flips:
        description += f"🔹 **{name}** - **{profit:,.0f}** coins profit\n"
        description += f"   🏷️ Craft Cost: {cost:,.0f} coins | 🏪 Lowest Price: {price:,.0f} coins\n\n"

    embed = discord.Embed(
        title="💰 Top 15 Craft Flips",
        description=description,
        color=discord.Color.gold()
    )
    await interaction.followup.send(embed=embed)

if __name__ == '__main__':
    bot.run(BOT_TOKEN)
