import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv
from flask import Flask
import random
import threading

# Initialize environment and bot
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Discord Bot setup
GUILD_ID = 1333567666983538718
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Hypixel API URLs
BAZAAR_API_URL = "https://api.hypixel.net/skyblock/bazaar"
ITEMS_API_URL = "https://api.hypixel.net/resources/skyblock/items"

# NEU GitHub
NEU_ITEMS_LISTING_URL = (
    "https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/contents/items"
)
NEU_ITEM_RAW_URL = (
    "https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/"
    "master/items/{}.json"
)

# Initialize Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        guild = discord.Object(id=GUILD_ID)
        # Clear old commands for this guild
        bot.tree.clear_commands(guild=guild)

        # Register the npcflip command
        bot.tree.add_command(npc_flip)
        # Register the NEW craftflip command (random recipe)
        bot.tree.add_command(craftflip)

        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
    except Exception as e:
        print(f"⚠️ Sync error: {e}")

@bot.tree.command(name="npcflip", description="Shows the top 15 NPC flips based on buy order and instant buy")
async def npc_flip(interaction: discord.Interaction):
    await interaction.response.defer()
    
    bazaar_data = await fetch_json(BAZAAR_API_URL)
    items_data = await fetch_json(ITEMS_API_URL)
    if not bazaar_data or "products" not in bazaar_data:
        return await interaction.followup.send("Failed to fetch Bazaar data.")
    if not items_data or "items" not in items_data:
        return await interaction.followup.send("Failed to fetch Items data.")
    
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
                flips.append((item_id, npc_sell_price - insta_buy_price, "insta", insta_buy_price))
            if buy_order_price > 0:
                flips.append((item_id, npc_sell_price - buy_order_price, "buyorder", buy_order_price))
    
    # Sort and grab top 15
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

#
# NEW /craftflip COMMAND that shows a RANDOM RECIPE from NEU
#
@bot.tree.command(name="craftflip", description="Grab a random recipe from the NEU repo and display it")
async def craftflip(interaction: discord.Interaction):
    await interaction.response.defer()
    # 1) Fetch the directory listing of NEU items
    files = await fetch_json(NEU_ITEMS_LISTING_URL)
    if not files or not isinstance(files, list):
        return await interaction.followup.send("Failed to fetch NEU items listing.")
    
    # 2) Pick a random .json file from the list
    random_file = random.choice(files)  # picks from the first 1000 if more than 1000 exist
    item_id = random_file["name"].replace(".json", "")

    # 3) Fetch the item data
    item_url = NEU_ITEM_RAW_URL.format(item_id)
    item_data = await fetch_json(item_url)
    if not item_data:
        return await interaction.followup.send(f"Failed to fetch item data for `{item_id}`.")

    # 4) Check for a "crafting" key
    crafting_info = item_data.get("crafting", {})
    if not crafting_info:
        return await interaction.followup.send(
            f"**{item_id}** doesn't seem to have a 'crafting' section."
        )

    mats = crafting_info.get("materials", [])
    if not mats:
        return await interaction.followup.send(
            f"**{item_id}** has a 'crafting' section but no 'materials' listed."
        )

    # Build a description from the materials
    recipe_description = f"**Random Item:** `{item_id}`\n\n"
    recipe_description += "**Recipe Materials**:\n"
    for mat in mats:
        mat_name = mat["id"]
        mat_count = mat["count"]
        recipe_description += f"- {mat_count}x {mat_name}\n"

    embed = discord.Embed(
        title=f"Random Recipe: {item_id}",
        description=recipe_description,
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed)

# Utility function to fetch JSON (bypassing MIME type checks)
async def fetch_json(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json(content_type=None)

# Run both the bot and Flask app
if __name__ == '__main__':
    def run_flask():
        app.run(host="0.0.0.0", port=8000)

    import random
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(BOT_TOKEN)
 