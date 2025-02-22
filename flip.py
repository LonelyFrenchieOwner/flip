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
GUILD_ID = 1333567666983538718
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Hypixel API URLs
BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
AUCTION_API_URL = "https://api.hypixel.net/skyblock/auctions"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"
NEU_ITEMS_URL = "https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/master/items/{}.json"

# Initialize Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

async def fetch_json(url: str):
    """Fetch JSON data from a URL with error logging"""
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

async def fetch_neu_items():
    """Fetch NEU item data from GitHub dynamically"""
    neu_data = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/contents/items") as response:
                if response.status != 200:
                    logging.error("Failed to fetch NEU items list.")
                    return neu_data
                
                files = await response.json()
                
                for file in files:
                    item_id = file["name"].replace(".json", "")
                    async with session.get(NEU_ITEMS_URL.format(item_id)) as item_response:
                        if item_response.status != 200:
                            logging.error(f"Failed to fetch data for item {item_id}")
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
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)

        # Register commands explicitly
        bot.tree.add_command(npc_flip)
        bot.tree.add_command(craft_flip)

        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
        
        # Debugging: List all registered commands
        logging.debug(f"Registered commands: {[cmd.name for cmd in bot.tree.get_commands()]}")

    except Exception as e:
        logging.error(f"⚠️ Sync error: {e}")

@bot.tree.command(name="npcflip", description="Shows the top 15 NPC flips based on buy order and instant buy")
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
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="craftflip", description="Shows the top 15 craft flips based on lowest BIN and Bazaar price")
async def craft_flip(interaction: discord.Interaction):
    await interaction.response.defer()

    bazaar_data = await fetch_json(BAZAAR_API_URL)
    auction_data = await fetch_json(AUCTION_API_URL)
    neu_items = await fetch_neu_items()

    if not bazaar_data or not auction_data or not neu_items:
        logging.error("Failed to fetch Bazaar, Auction, or NEU items data.")
        return await interaction.followup.send("Failed to fetch necessary data.")

    lowest_bin = {}
    for auction in auction_data.get("auctions", []):
        if auction.get("bin", False):
            item_id = auction.get("item_name", "").replace(" ", "_").upper()
            price = auction["starting_bid"]
            if item_id not in lowest_bin or price < lowest_bin[item_id]:
                lowest_bin[item_id] = price

    flips = []
    for item_id, item_data in neu_items.items():
        craft_cost = sum(
            bazaar_data["products"].get(mat["id"], {}).get("quick_status", {}).get("sellPrice", 0) * mat["count"]
            for mat in item_data.get("crafting", {}).get("materials", [])
        )

        if craft_cost > 0:
            lowest_price = min(lowest_bin.get(item_id, float('inf')), bazaar_data["products"].get(item_id, {}).get("quick_status", {}).get("sellPrice", float('inf')))
            profit = lowest_price - craft_cost
            flips.append((item_id.replace("_", " ").title(), profit, craft_cost, lowest_price))

    top_flips = sorted(flips, key=lambda x: x[1], reverse=True)[:15]

    description = "**Top 15 Craft Flips**\n\n"
    for name, profit, cost, price in top_flips:
        description += f"🔹 **{name}** - **{profit:,.0f}** coins profit\n"
        description += f"   🏷️ Craft Cost: {cost:,.0f} coins | 🏪 Lowest Price: {price:,.0f} coins\n\n"

    embed = discord.Embed(title="💰 Top 15 Craft Flips", description=description, color=discord.Color.gold())
    await interaction.followup.send(embed=embed)

if __name__ == '__main__':
    bot.run(BOT_TOKEN)
