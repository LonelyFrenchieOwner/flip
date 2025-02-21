import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")


# Your server (guild) ID
GUILD_ID = 1333567666983538718

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.add_command(npc_flip)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
    except Exception as e:
        print(f"⚠️ Sync error: {e}")

@bot.tree.command(name="npcflip", description="Shows the top 15 NPC flips based on buy order and instant buy")
async def npc_flip(interaction: discord.Interaction):
    await interaction.response.defer()
    
    bazaar_data = await fetch_json(BAZAAR_API_URL)
    items_data = await fetch_json(ITEMS_API_URL)
    if "products" not in bazaar_data or "items" not in items_data:
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

async def fetch_json(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

bot.run(BOT_TOKEN)