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

        # Register the new /craftflip command
        bot.tree.add_command(craftflip)

        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}.")
    except Exception as e:
        print(f"⚠️ Sync error: {e}")

@bot.tree.command(name="craftflip", description="Grab a random recipe from the NEU repo and display it")
async def craftflip(interaction: discord.Interaction):
    """Picks one random .json file from the NEU repo and tries to show its recipe."""
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

    # 4) Check if there's a 'crafting' field or a 'recipe' field
    crafting_info = item_data.get("crafting", {})
    recipe_info = item_data.get("recipe", {})

    if crafting_info:
        # Some NEU items store recipes in "crafting" -> "materials"
        materials = crafting_info.get("materials", [])
        if not materials:
            return await interaction.followup.send(
                f"**{item_id}** has 'crafting' but no 'materials' array."
            )
        desc = f"**Random Item:** `{item_id}`\n\n**Crafting Materials**:\n"
        for mat in materials:
            mat_name = mat["id"]
            mat_count = mat["count"]
            desc += f"- {mat_count}x {mat_name}\n"

    elif recipe_info:
        # Others (like ARMOR_OF_YOG_LEGGINGS) store recipes in "recipe" -> {A1, A2, ..., C3}
        desc = f"**Random Item:** `{item_id}`\n\n**3×3 Recipe**:\n"
        for row_label in ["A", "B", "C"]:
            row_str = ""
            for col_num in ["1", "2", "3"]:
                slot = row_label + col_num
                slot_val = recipe_info.get(slot, "Empty")
                row_str += f"[{slot_val}] "
            desc += f"{row_label} row: {row_str}\n"

    else:
        return await interaction.followup.send(
            f"**{item_id}** doesn't have a 'crafting' or 'recipe' section."
        )

    embed = discord.Embed(
        title=f"Random Recipe: {item_id}",
        description=desc,
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed)

async def fetch_json(url: str):
    """Fetch JSON data from a URL using content_type=None to bypass MIME issues."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json(content_type=None)

# Run both the bot and Flask app
def run_flask():
    app.run(host="0.0.0.0", port=8000)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(BOT_TOKEN)
