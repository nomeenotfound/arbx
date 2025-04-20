import logging
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, Chat, Message
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional, Tuple
import json
import re
from aiohttp import ClientTimeout
from collections import defaultdict
import time

# Optional imports for file operations (wrap in try/except)
try:
    import aiofiles
except ImportError:
    aiofiles = None
    logging.warning("aiofiles not installed, file operations will be disabled")

# ✅ SECURITY
ADMIN_USER_IDS = [6564992653, 6385733028, 1868216502]  # List of admin user IDs

# ✅ TOKENS
BOT_TOKEN = "7694639215:AAH7igSlJIBmCF9pjUJM95c-Db72fYpcBJE"
ODDS_API_KEY = "79a34ed9af6d77b01ed6cfcb654afc96"  # Need a new valid API key

# ✅ LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Set more detailed logging for our module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# API configuration
API_TIMEOUT = ClientTimeout(total=10)  # Reduced timeout
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# 🎛 SETTINGS
SELECTING, BOOKIES, THRESHOLD, AUTO_REFRESH, STAKE_AMOUNT, TOOLS = range(6)
DEFAULT_BOOKIES = [
    "1xBet", 
    "Rajabet", 
    "Dafabet", 
    "1Win", 
    "BC.Game", 
    "Hash.game",
    "Parimatch",
    "Melbet",
    "Mostbet",
    "Betwinner",
    "22Bet",
    "10Cric"
]

# Sports and Markets Configuration
SPORTS = [
    # Soccer Leagues
    "soccer_epl",  # English Premier League
    "soccer_uefa_champs_league",  # Champions League
    "soccer_spain_la_liga",  # La Liga
    "soccer_italy_serie_a",  # Serie A
    "soccer_germany_bundesliga",  # Bundesliga
    "soccer_france_ligue_one",  # Ligue 1
    "soccer_fifa_world_cup",  # World Cup
    
    # Tennis
    "tennis_wta_us_open",  # WTA US Open
    "tennis_wta_wimbledon",  # WTA Wimbledon
    
    # Other popular sports
    "basketball_nba",  # NBA
    "americanfootball_nfl",  # NFL
    "mma_mixed_martial_arts",  # MMA/UFC
    "boxing_boxing",  # Boxing
]

MARKETS = [
    "h2h",  # Match Winner
    "spreads",  # Handicap
    "totals",  # Over/Under
]

# Bookie URLs and configurations
BOOKIE_CONFIGS = {
    # Indian Focused
    "10Cric": {
        "url": "https://www.10cric.com/sports/cricket",
        "type": "indian",
        "reliability": "medium"
    },
    
    # Shady/Offshore (Available in India)
    "1xBet": {
        "url": "https://1xbet.com/en/live",
        "type": "offshore",
        "reliability": "low"
    },
    "Rajabet": {
        "url": "https://rajabet.com/sports",
        "type": "offshore",
        "reliability": "low"
    },
    "Dafabet": {
        "url": "https://www.dafabet.com/en/sports",
        "type": "offshore",
        "reliability": "medium"
    },
    "1Win": {
        "url": "https://1win.com/live",
        "type": "offshore",
        "reliability": "low"
    },
    "BC.Game": {
        "url": "https://bc.game/sports",
        "type": "crypto",
        "reliability": "low"
    },
    "Hash.game": {
        "url": "https://hash.game/sports",
        "type": "crypto",
        "reliability": "low"
    },
    "Parimatch": {
        "url": "https://parimatch.com/en/sports",
        "type": "offshore",
        "reliability": "medium"
    },
    "Melbet": {
        "url": "https://melbet.com/en/live",
        "type": "offshore",
        "reliability": "low"
    },
    "Mostbet": {
        "url": "https://mostbet.com/en/live",
        "type": "offshore",
        "reliability": "low"
    },
    "Betwinner": {
        "url": "https://betwinner.com/en/live",
        "type": "offshore",
        "reliability": "low"
    },
    "22Bet": {
        "url": "https://22bet.com/en/live",
        "type": "offshore",
        "reliability": "low"
    }
}

# Update rate limiting to be much more lenient
RATE_LIMIT = 30  # Increased from 10 to 30 requests per minute
RATE_LIMIT_WINDOW = 30  # Reduced from 60 to 30 seconds
rate_limit_dict = defaultdict(list)

def is_rate_limited(user_id: int) -> bool:
    """Check if user has exceeded rate limit"""
    current_time = time.time()
    user_requests = rate_limit_dict[user_id]
    
    # Remove requests older than RATE_LIMIT_WINDOW seconds
    user_requests = [req for req in user_requests if current_time - req < RATE_LIMIT_WINDOW]
    rate_limit_dict[user_id] = user_requests
    
    # Check if user has exceeded rate limit
    if len(user_requests) >= RATE_LIMIT:
        logging.warning(f"User {user_id} rate limited")
        return True
    
    # Add current request
    user_requests.append(current_time)
    return False

async def fetch_odds(session: aiohttp.ClientSession, sport: str, market: str) -> Optional[List]:
    """Fetch odds with caching and error handling"""
    cache_key = f"{sport}_{market}"
    current_time = time.time()
    
    if cache_key in odds_cache:
        cache_time, cached_data = odds_cache[cache_key]
        if current_time - cache_time < CACHE_DURATION.total_seconds():
            return cached_data
    
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us,uk,au",
        "markets": market,
        "oddsFormat": "decimal"
    }
    
    try:
        async with session.get(url, params=params, headers=API_HEADERS, timeout=API_TIMEOUT) as resp:
            if resp.status == 429:  # Rate limit exceeded
                logging.warning(f"API rate limit exceeded for {sport} {market}")
                return None
            elif resp.status == 401:  # Invalid API key
                logging.error("Invalid API key")
                return None
            elif resp.status != 200:
                logging.error(f"API error: {resp.status} for {sport} {market}")
                return None
            
            data = await resp.json()
            odds_cache[cache_key] = (current_time, data)
            return data
    except asyncio.TimeoutError:
        logging.error(f"API request timed out for {sport} {market}")
        return None
    except Exception as e:
        logging.error(f"Error fetching odds for {sport} {market}: {e}")
        return None

# Add this global variable at the top with other globals
last_arb_match = {}

async def process_match(match: Dict, market: str, selected_bookies: List[str], stake_amount: int, threshold: float) -> Optional[Tuple[str, Dict]]:
    """Process a single match for arbitrage opportunities"""
    bookies = match.get("bookmakers", [])
    if len(bookies) < 2:
        return None

    filtered_bookies = [b for b in bookies if b["title"] in selected_bookies]
    if len(filtered_bookies) < 2:
        return None
    
    logging.debug(f"Processing match: {match['home_team']} vs {match['away_team']} with {len(filtered_bookies)} bookies")

    best_opportunity = None
    best_profit = 0
    match_data = None

    for i in range(len(filtered_bookies)):
        for j in range(i+1, len(filtered_bookies)):
            market_data1 = next((m for m in filtered_bookies[i]["markets"] if m["key"] == market), None)
            market_data2 = next((m for m in filtered_bookies[j]["markets"] if m["key"] == market), None)
            
            if not market_data1 or not market_data2:
                continue
                
            outcomes1 = market_data1["outcomes"]
            outcomes2 = market_data2["outcomes"]
            
            if len(outcomes1) != len(outcomes2):
                continue
            
            # Special case: if there are only 2 outcomes, we can try to force an arbitrage opportunity
            if len(outcomes1) == 2:
                # For each outcome, find the best odds from both bookmakers
                best_odds = []
                for idx in range(len(outcomes1)):
                    best_odds.append(max(float(outcomes1[idx]["price"]), float(outcomes2[idx]["price"])))
                
                # Calculate implied probabilities of the best odds
                implied_probs = [1/odds for odds in best_odds]
                total = sum(implied_probs)
                
                # If total implied probability is less than 1, we have an arbitrage opportunity
                if total < 1:
                    profit_margin = round((1 - total) * 100, 2)
                    logging.info(f"Found synthetic arbitrage: {match['home_team']} vs {match['away_team']} with {profit_margin}% profit")
                    
                    # Create a synthetic opportunity between the best odds
                    best_profit = profit_margin
                    stake_distribution = [(1/odds)/total for odds in best_odds]
                    stake_amounts = [round(stake_amount * dist) for dist in stake_distribution]
                    profit = round(stake_amount * profit_margin / 100)
                    
                    # Format match information
                    sport_name = match["sport_key"].split('_')[0].capitalize()
                    league_name = ' '.join(match["sport_key"].split('_')[1:]).upper()
                    match_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00'))
                    match_time = match_time.astimezone()
                    time_str = match_time.strftime("%d %b %Y, %I:%M %p")
                    
                    best_opportunity = (
                        f"🚨 *ARBX FIND* | Created by NXMAN\n\n"
                        f"⚽ Sport: *{sport_name}*\n"
                        f"🏆 League: *{league_name}*\n"
                        f"⏰ Time: *{time_str}*\n\n"
                        f"⚔️ Match: *{match['home_team']} vs {match['away_team']}*\n"
                        f"🏆 Market: *{market}*\n"
                        f"💸 Arbitrage Profit: *+{profit_margin}%*\n"
                    )
                    
                    # Add the best odds for each outcome
                    for idx in range(len(outcomes1)):
                        if best_odds[idx] == float(outcomes1[idx]["price"]):
                            best_opportunity += f"✅ {filtered_bookies[i]['title']}: {outcomes1[idx]['name']} @ {outcomes1[idx]['price']}\n"
                        else:
                            best_opportunity += f"✅ {filtered_bookies[j]['title']}: {outcomes2[idx]['name']} @ {outcomes2[idx]['price']}\n"
                    
                    best_opportunity += f"\n🧠 STAKE SPLIT (₹{stake_amount:,}):\n"
                    for idx in range(len(outcomes1)):
                        best_opportunity += f"- ₹{stake_amounts[idx]:,} on {outcomes1[idx]['name']}\n"
                    
                    best_opportunity += f"\n💰 *RISK-FREE PROFIT:* ₹{profit:,}\n\n"
                    best_opportunity += f"⚠️ *Bookie Reliability:*\n"
                    best_opportunity += f"- {filtered_bookies[i]['title']}: {BOOKIE_CONFIGS[filtered_bookies[i]['title']]['reliability'].upper()}\n"
                    best_opportunity += f"- {filtered_bookies[j]['title']}: {BOOKIE_CONFIGS[filtered_bookies[j]['title']]['reliability'].upper()}"
                    
                    match_data = {
                        "sport": match["sport_key"],
                        "home_team": match["home_team"],
                        "away_team": match["away_team"],
                        "market": market,
                        "bookie1": filtered_bookies[i]["title"],
                        "bookie2": filtered_bookies[j]["title"],
                        "outcome1": outcomes1[0]["name"],
                        "outcome2": outcomes2[0]["name"]
                    }
                    continue
            
            # Standard approach for all outcomes
            total = sum(min(1/float(o1["price"]), 1/float(o2["price"])) 
                       for o1, o2 in zip(outcomes1, outcomes2))

            # Changed from 1.05 to 1.10 to find more opportunities even with higher totals
            if total < 1.10:
                profit_margin = round((1 - total) * 100, 2)
                
                # Accept any positive margin
                if profit_margin > 0:
                    logging.info(f"Found arbitrage opportunity: {match['home_team']} vs {match['away_team']} with {profit_margin}% profit")
                    
                    if profit_margin > best_profit:
                        best_profit = profit_margin
                        stake_team1 = round(stake_amount * (1 / float(outcomes1[0]["price"])) / total)
                        stake_team2 = stake_amount - stake_team1
                        profit = round(stake_amount * profit_margin / 100)

                        # Format match information
                        sport_name = match["sport_key"].split('_')[0].capitalize()
                        league_name = ' '.join(match["sport_key"].split('_')[1:]).upper()
                        match_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00'))
                        match_time = match_time.astimezone()
                        time_str = match_time.strftime("%d %b %Y, %I:%M %p")

                        market_name = {
                            "h2h": "Match Winner",
                            "spreads": "Handicap",
                            "totals": "Over/Under",
                            "btts": "Both Teams To Score",
                            "draw_no_bet": "Draw No Bet",
                            "double_chance": "Double Chance",
                            "alternate_spreads": "Alternate Handicap",
                            "alternate_totals": "Alternate Over/Under",
                            "team_totals": "Team Points",
                            "winning_margin": "Margin of Victory",
                            "race_to_points": "Race to Points",
                            "player_points": "Player Points"
                        }.get(market, market)

                        best_opportunity = (
                            f"🚨 *ARBX FIND* | Created by NXMAN\n\n"
                            f"⚽ Sport: *{sport_name}*\n"
                            f"🏆 League: *{league_name}*\n"
                            f"⏰ Time: *{time_str}*\n\n"
                            f"⚔️ Match: *{match['home_team']} vs {match['away_team']}*\n"
                            f"🏆 Market: *{market_name}*\n"
                            f"💸 Arbitrage Profit: *+{profit_margin}%*\n"
                            f"✅ {filtered_bookies[i]['title']}: {outcomes1[0]['name']} @ {outcomes1[0]['price']}\n"
                            f"✅ {filtered_bookies[j]['title']}: {outcomes2[0]['name']} @ {outcomes2[0]['price']}\n\n"
                            f"🧠 STAKE SPLIT (₹{stake_amount:,}):\n"
                            f"- ₹{stake_team1:,} on {outcomes1[0]['name']}\n"
                            f"- ₹{stake_team2:,} on {outcomes2[0]['name']}\n\n"
                            f"💰 *RISK-FREE PROFIT:* ₹{profit:,}\n\n"
                            f"⚠️ *Bookie Reliability:*\n"
                            f"- {filtered_bookies[i]['title']}: {BOOKIE_CONFIGS[filtered_bookies[i]['title']]['reliability'].upper()}\n"
                            f"- {filtered_bookies[j]['title']}: {BOOKIE_CONFIGS[filtered_bookies[j]['title']]['reliability'].upper()}"
                        )
                        match_data = {
                            "sport": match["sport_key"],
                            "home_team": match["home_team"],
                            "away_team": match["away_team"],
                            "market": market,
                            "bookie1": filtered_bookies[i]["title"],
                            "bookie2": filtered_bookies[j]["title"],
                            "outcome1": outcomes1[0]["name"],
                            "outcome2": outcomes2[0]["name"]
                        }

    if best_opportunity:
        return best_opportunity, match_data
    return None

async def fetch_arbitrage_opportunity(update: Update):
    user_id = update.effective_user.id
    user_setting = user_settings.get(user_id, {})
    stake_amount = user_setting.get("stake_amount", 1000)
    threshold = user_setting.get("threshold", 0.5)
    selected_bookies = user_setting.get("bookies", DEFAULT_BOOKIES)
    
    logging.info(f"Starting arbitrage search with threshold {threshold}% and {len(selected_bookies)} bookies")
    opportunities = []
    
    async with aiohttp.ClientSession() as session:
        # Fetch odds from API
        api_tasks = []
        
        # API tasks for each sport and market
        for sport in SPORTS:
            for market in MARKETS:
                api_tasks.append(fetch_odds(session, sport, market))
        
        logging.info(f"Fetching odds for {len(api_tasks)} sport/market combinations")
        
        # Gather all results
        api_results = await asyncio.gather(*api_tasks)
        
        valid_results = [r for r in api_results if r is not None]
        logging.info(f"Received {len(valid_results)} valid API responses out of {len(api_tasks)} requests")
        
        # Process API results
        match_count = 0
        for data in api_results:
            if not data:
                continue
                
            for match in data:
                match_count += 1
                # Process each match for arbitrage opportunities
                arb_result = await process_match(
                    match, 
                    market, 
                    selected_bookies, 
                    stake_amount, 
                    threshold
                )
                if arb_result:
                    # Convert commence_time to timestamp for comparison
                    commence_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00'))
                    opportunities.append((arb_result, commence_time.timestamp()))
        
        logging.info(f"Processed {match_count} matches and found {len(opportunities)} arbitrage opportunities")
        
        # Sort opportunities by profit margin
        opportunities.sort(key=lambda x: float(x[0].split("Arbitrage Profit: *+")[1].split("%*")[0]), reverse=True)
        
        # Return the best opportunity if any found
        if opportunities:
            logging.info(f"Returning best arbitrage opportunity with profit margin: {opportunities[0][0].split('Arbitrage Profit: *+')[1].split('%*')[0]}%")
            return opportunities[0][0]
        
        logging.info("No arbitrage opportunities found")
        return None

# ✅ ACCESS CONTROL
def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_USER_IDS

async def deny_access(update: Update):
    await update.message.reply_text(
        "❌ Access Denied\n\nDM @nxmanmusic to Buy Access For ArbX Pro"
    )

# Add at the top with other constants
BRANDING = "ᴍᴀᴅᴇ ʙʏ @nxmanmusic"  # Using small caps for subtlety

# Add this mapping at the top with other constants
USER_NAMES = {
    6564992653: "Numan",
    6385733028: "Ubaiz",
    1868216502: "Hanan"
}

# ✅ /start COMMAND
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_rate_limited(user_id):
        await update.message.reply_text(
            f"⚠️ Rate limit exceeded. Please wait a minute before trying again.\n\n_{BRANDING}_",
            parse_mode="Markdown"
        )
        return
    
    if not is_admin(update):
        return await deny_access(update)

    # Get user's name from mapping
    user_name = USER_NAMES.get(user_id, "User")
    
    keyboard = [
        [InlineKeyboardButton("🔍 Get Arbitrage Alert", callback_data='get_alert')],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data='settings'),
            InlineKeyboardButton("🛠 Tools", callback_data='tools'),
        ],
        [InlineKeyboardButton("ℹ️ How It Works", callback_data='how_it_works')],
    ]
    
    await update.message.reply_text(
        f"🇮🇳 *Welcome to ArbX - India's Premier Arbitrage Bot*\n\n"
        f"👋 Welcome, *{user_name}*\n\n"
        f"🔍 Real-time arbitrage detection for Indian bettors\n"
        f"📈 Scanning Indian and offshore bookmakers\n"
        f"💰 Customizable stake amounts in INR\n"
        f"🚀 Created by *NXMAN*\n\n"
        f"_{BRANDING}_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ✅ CALLBACKS
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if is_rate_limited(update.effective_user.id):
        await query.message.reply_text(
            f"⚠️ Rate limit exceeded. Please wait a minute before trying again.\n\n_{BRANDING}_",
            parse_mode="Markdown"
        )
        return
    
    if not is_admin(update):
        return await deny_access(update)

    if query.data == "get_alert":
        progress_message = await query.message.edit_text(f"🔍 Searching for arbitrage opportunities...\n\n_{BRANDING}_", parse_mode="Markdown")
        
        # Show searching progress
        for i in range(3):
            await asyncio.sleep(1)
            await progress_message.edit_text(f"🔍 Searching for arbitrage opportunities{'.' * (i+1)}\n\nChecking bookmakers and odds...\n\n_{BRANDING}_", parse_mode="Markdown")
        
        result = await fetch_arbitrage_opportunity(update)
        if result:
            alert, match_data = result
            if alert in alerts_cache:
                await query.message.edit_text(f"⚠️ No new arbitrage found. Returning to main menu in 3 seconds...\n\n_{BRANDING}_", parse_mode="Markdown")
                await asyncio.sleep(3)
                # Return to main menu
                keyboard = [
                    [InlineKeyboardButton("🔍 Get Arbitrage Alert", callback_data='get_alert')],
                    [
                        InlineKeyboardButton("⚙️ Settings", callback_data='settings'),
                        InlineKeyboardButton("🛠 Tools", callback_data='tools'),
                    ],
                    [InlineKeyboardButton("ℹ️ How It Works", callback_data='how_it_works')],
                ]
                await query.message.edit_text(
                    f"🇮🇳 *Welcome to ArbX - India's Premier Arbitrage Bot*\n\n"
                    f"👋 Welcome, *{USER_NAMES.get(update.effective_user.id, 'User')}*\n\n"
                    f"🔍 Real-time arbitrage detection for Indian bettors\n"
                    f"📈 Scanning Indian and offshore bookmakers\n"
                    f"💰 Customizable stake amounts in INR\n"
                    f"🚀 Created by *NXMAN*\n\n"
                    f"_{BRANDING}_",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            else:
                last_arb_match[update.effective_user.id] = match_data
                keyboard = [
                    [InlineKeyboardButton("🔄 Refresh Odds", callback_data='refresh_arb')],
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
                ]
                await query.message.edit_text(
                    f"{alert}\n\n_{BRANDING}_",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                alerts_cache[alert] = datetime.now()
        else:
            await query.message.edit_text(
                f"⚠️ No arbitrage found at the moment.\n\n"
                f"We checked {len(SPORTS)} sports and {len(MARKETS)} markets.\n"
                f"Try adjusting your settings or try again later.\n\n"
                f"Returning to main menu in 3 seconds...\n\n"
                f"_{BRANDING}_", 
                parse_mode="Markdown"
            )
            await asyncio.sleep(3)
            # Return to main menu
            keyboard = [
                [InlineKeyboardButton("🔍 Get Arbitrage Alert", callback_data='get_alert')],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data='settings'),
                    InlineKeyboardButton("🛠 Tools", callback_data='tools'),
                ],
                [InlineKeyboardButton("ℹ️ How It Works", callback_data='how_it_works')],
            ]
            await query.message.edit_text(
                f"🇮🇳 *Welcome to ArbX - India's Premier Arbitrage Bot*\n\n"
                f"👋 Welcome, *{USER_NAMES.get(update.effective_user.id, 'User')}*\n\n"
                f"🔍 Real-time arbitrage detection for Indian bettors\n"
                f"📈 Scanning Indian and offshore bookmakers\n"
                f"💰 Customizable stake amounts in INR\n"
                f"🚀 Created by *NXMAN*\n\n"
                f"_{BRANDING}_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
    
    elif query.data == "settings":
        await settings_menu(update, context)
    
    elif query.data == "tools":
        keyboard = [
            [InlineKeyboardButton("🧮 Kelly Calculator", callback_data='kelly_calc')],
            [InlineKeyboardButton("📊 Arbitrage Calculator", callback_data='arb_calc')],
            [InlineKeyboardButton("💹 Value Bet Finder", callback_data='value_bet')],
            [InlineKeyboardButton("📈 Odds Converter", callback_data='odds_convert')],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
        ]
        await query.message.edit_text(
            "🛠 *Betting Tools*\n\n"
            "Select a tool to use:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif query.data == "how_it_works":
        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
        ]
        await query.message.edit_text(
            "💡 *How ArbX Works*\n\n"
            "ArbX is India's premier arbitrage bot, scanning Indian and offshore bookmakers\n"
            "to find guaranteed-profit betting opportunities using real-time odds.\n\n"
            "🔍 *Features:*\n"
            "- Customizable stake amounts in INR\n"
            "- Focus on India-available bookmakers\n"
            "- Real-time arbitrage detection\n"
            "- Detailed stake splits and profit calculations\n\n"
            "🛠 Built by *NXMAN*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif query.data == "back":
        keyboard = [
            [InlineKeyboardButton("🔍 Get Arbitrage Alert", callback_data='get_alert')],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data='settings'),
                InlineKeyboardButton("🛠 Tools", callback_data='tools'),
            ],
            [InlineKeyboardButton("ℹ️ How It Works", callback_data='how_it_works')],
        ]
        await query.message.edit_text(
            "🇮🇳 *Welcome to ArbX - India's Premier Arbitrage Bot*\n\n"
            "🔍 Real-time arbitrage detection for Indian bettors\n"
            "📈 Scanning Indian and offshore bookmakers\n"
            "💰 Customizable stake amounts in INR\n"
            "🚀 Created by *NXMAN*\n\n"
            f"_{BRANDING}_",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    # Tool handlers
    elif query.data == "kelly_calc":
        await query.message.edit_text(
            "🧮 *Kelly Calculator*\n\n"
            "Enter odds, probability, and bankroll separated by spaces\n"
            "Example: 2.0 0.5 1000",
            parse_mode="Markdown"
        )
    elif query.data == "arb_calc":
        await query.message.edit_text(
            "📊 *Arbitrage Calculator*\n\n"
            "Enter odds for each outcome separated by spaces, followed by stake amount\n"
            "Example: 2.0 1.8 1000",
            parse_mode="Markdown"
        )
    elif query.data == "value_bet":
        await query.message.edit_text(
            "💹 *Value Bet Finder*\n\n"
            "Enter: market_odds true_probability min_edge\n"
            "Example: 2.0 0.55 5",
            parse_mode="Markdown"
        )
    elif query.data == "odds_convert":
        await query.message.edit_text(
            "📈 *Odds Converter*\n\n"
            "Enter odds to convert (decimal format)\n"
            "Example: 2.0",
            parse_mode="Markdown"
        )

    elif query.data == "refresh_arb":
        await refresh_arbitrage(update, context)

# ✅ SETTINGS SYSTEM
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_settings:
        user_settings[user_id] = {
            "bookies": DEFAULT_BOOKIES,
            "threshold": 0.1,  # Lowered default threshold to 0.1%
            "auto_refresh": False,
            "stake_amount": 1000,
        }

    current_settings = user_settings[user_id]
    keyboard = [
        [InlineKeyboardButton("📊 Set Profit Threshold", callback_data='set_threshold')],
        [InlineKeyboardButton("🏦 Select Bookmakers", callback_data='set_bookies')],
        [InlineKeyboardButton("💰 Set Stake Amount", callback_data='set_stake')],
        [InlineKeyboardButton("🔁 Toggle Auto-Refresh", callback_data='toggle_refresh')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
    ]
    
    settings_text = (
        "⚙️ *Current Settings*\n\n"
        f"📊 Profit Threshold: >{current_settings['threshold']}%\n"
        f"💰 Stake Amount: ₹{current_settings['stake_amount']:,}\n"
        f"🔁 Auto-Refresh: {'✅ On' if current_settings['auto_refresh'] else '❌ Off'}\n\n"
        "Select an option to modify:"
    )
    
    await update.callback_query.message.edit_text(
        settings_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECTING

# ✅ HANDLING THE THRESHOLD SETTING
async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("> 0.5%", callback_data='threshold_0.5')],
        [InlineKeyboardButton("> 1%", callback_data='threshold_1')],
        [InlineKeyboardButton("> 2%", callback_data='threshold_2')],
        [InlineKeyboardButton("> 3%", callback_data='threshold_3')],
        [InlineKeyboardButton("⬅️ Back", callback_data='settings')]
    ]
    await update.callback_query.message.reply_text(
        "🔧 Select Minimum Profit Threshold:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return THRESHOLD

async def handle_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    threshold = float(query.data.split('_')[1])
    
    user_id = update.effective_user.id
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id]["threshold"] = threshold
    
    await query.message.reply_text(f"✅ Profit threshold set to >{threshold}%")
    return await settings_menu(update, context)

# ✅ HANDLING THE BOOKIE SELECTION
async def set_bookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_bookies = user_settings.get(user_id, {}).get("bookies", DEFAULT_BOOKIES)
    
    keyboard = []
    for bookie in DEFAULT_BOOKIES:
        status = "✅" if bookie in current_bookies else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} {bookie}", callback_data=f"toggle_{bookie}")])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='settings')])
    
    await update.callback_query.message.reply_text(
        "🔧 Select your preferred bookmakers:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BOOKIES

# ✅ HANDLING BOOKIE TOGGLE
async def handle_bookie_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookie = query.data.split('_')[1]
    
    user_id = update.effective_user.id
    if user_id not in user_settings:
        user_settings[user_id] = {"bookies": []}
    
    current_bookies = user_settings[user_id].get("bookies", [])
    if bookie in current_bookies:
        current_bookies.remove(bookie)
    else:
        current_bookies.append(bookie)
    
    user_settings[user_id]["bookies"] = current_bookies
    return await set_bookies(update, context)

# ✅ HANDLING AUTO-REFRESH TOGGLE
async def toggle_auto_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_value = user_settings.get(user_id, {}).get("auto_refresh", False)
    user_settings[user_id]["auto_refresh"] = not current_value
    status = "enabled" if not current_value else "disabled"
    await update.callback_query.message.reply_text(
        f"Auto-refresh mode has been {status}.",
        parse_mode="Markdown"
    )
    return AUTO_REFRESH

# ✅ HANDLING STAKE AMOUNT SETTING
async def set_stake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "💰 Enter your preferred stake amount in INR (e.g., 1000, 5000, 10000):"
    )
    return STAKE_AMOUNT

async def handle_stake_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stake = int(update.message.text)
        if stake < 100:
            await update.message.reply_text("❌ Minimum stake amount is ₹100")
            return STAKE_AMOUNT
        if stake > 100000:
            await update.message.reply_text("❌ Maximum stake amount is ₹1,00,000")
            return STAKE_AMOUNT
        
        user_id = update.effective_user.id
        if user_id not in user_settings:
            user_settings[user_id] = {}
        user_settings[user_id]["stake_amount"] = stake
        
        await update.message.reply_text(f"✅ Stake amount set to ₹{stake:,}")
        return await settings_menu(update, context)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number")
        return STAKE_AMOUNT

# Add tools menu handler
async def tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🧮 Kelly Calculator", callback_data='kelly_calc')],
        [InlineKeyboardButton("📊 Arbitrage Calculator", callback_data='arb_calc')],
        [InlineKeyboardButton("💹 Value Bet Finder", callback_data='value_bet')],
        [InlineKeyboardButton("📈 Odds Converter", callback_data='odds_convert')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
    ]
    
    await update.callback_query.message.edit_text(
        "🛠 *Betting Tools*\n\n"
        "Select a tool to use:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return TOOLS

# Implement missing tool handlers
async def handle_kelly_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        # Parse input values
        odds, prob, bankroll = map(float, query.message.text.split())
        
        # Calculate Kelly criterion
        result = await calculate_kelly_criterion(odds, prob, bankroll)
        
        if "error" in result:
            await query.message.reply_text(f"❌ Error: {result['error']}")
        else:
            response = (
                f"🧮 *Kelly Criterion Results*\n\n"
                f"💰 Optimal stake: ₹{result['stake']:,.2f}\n"
                f"📊 Kelly percentage: {result['percentage']}%\n"
                f"📈 Expected value: ₹{result['expected_value']:,.2f}"
            )
            await query.message.reply_text(response, parse_mode="Markdown")
    except ValueError:
        await query.message.reply_text(
            "❌ Invalid input format. Please use: odds probability bankroll\n"
            "Example: 2.0 0.5 1000"
        )
    return TOOLS

async def handle_arb_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "Enter odds for each outcome separated by spaces, followed by stake amount\n"
        "Example: 2.0 1.8 1000"
    )
    return TOOLS

async def handle_value_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "Enter: market_odds true_probability min_edge\n"
        "Example: 2.0 0.55 5"
    )
    return TOOLS

async def handle_odds_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "Enter odds to convert (decimal format)\n"
        "Example: 2.0"
    )
    return TOOLS

# Simple cache cleanup
async def cleanup_caches(context: ContextTypes.DEFAULT_TYPE):
    """Clean up expired cache entries"""
    current_time = time.time()  # Use timestamp for consistency
    
    # Clean odds cache
    expired_odds = [
        key for key, (cache_time, _) in odds_cache.items()
        if current_time - cache_time > CACHE_DURATION.total_seconds()
    ]
    for key in expired_odds:
        del odds_cache[key]
    
    # Clean alerts cache
    global alerts_cache
    alerts_cache = {}  # Just clear it completely to avoid type issues
    
    # Clean rate limit dictionary
    for user_id in list(rate_limit_dict.keys()):
        rate_limit_dict[user_id] = [
            req for req in rate_limit_dict[user_id]
            if current_time - req < 60
        ]
        if not rate_limit_dict[user_id]:
            del rate_limit_dict[user_id]

# Add persistent storage for user settings
async def save_user_settings():
    """Save user settings to file"""
    if aiofiles is None:
        logging.warning("aiofiles not installed, cannot save user settings")
        return
    try:
        async with aiofiles.open('user_settings.json', 'w') as f:
            await f.write(json.dumps(user_settings))
    except Exception as e:
        logging.error(f"Error saving user settings: {e}")

async def load_user_settings():
    """Load user settings from file"""
    if aiofiles is None:
        logging.warning("aiofiles not installed, cannot load user settings")
        return {}
    try:
        async with aiofiles.open('user_settings.json', 'r') as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.error(f"Error loading user settings: {e}")
        return {}

# Modify main function to load settings
async def init_app():
    """Initialize application state"""
    global user_settings
    user_settings = await load_user_settings()

# Initialize global variables
user_settings = {}
alerts_cache = {}
odds_cache = {}
CACHE_DURATION = timedelta(minutes=5)
last_alert_time = {}  # Store timestamps instead of datetime objects

# Tools section functions
async def calculate_kelly_criterion(odds: float, prob: float, bankroll: float) -> Dict:
    """Calculate optimal bet size using Kelly Criterion"""
    if prob <= 0 or prob >= 1:
        return {"error": "Invalid probability"}
    
    b = odds - 1  # Decimal odds to fractional
    q = 1 - prob
    
    kelly = (b * prob - q) / b
    if kelly < 0:
        return {"stake": 0, "explanation": "No value bet found"}
    
    stake = round(kelly * bankroll, 2)
    return {
        "stake": stake,
        "percentage": round(kelly * 100, 2),
        "expected_value": round(stake * (prob * odds - 1), 2)
    }

async def calculate_arbitrage_stakes(odds_list: List[float], total_stake: float) -> Dict:
    """Calculate optimal stakes for arbitrage betting"""
    implied_probs = [1/odd for odd in odds_list]
    total_implied = sum(implied_probs)
    
    if total_implied >= 1:
        return {"error": "No arbitrage opportunity"}
    
    stakes = [round((1/odd)/total_implied * total_stake, 2) for odd in odds_list]
    profit = round(total_stake * (1 - total_implied), 2)
    
    return {
        "stakes": stakes,
        "profit": profit,
        "roi": round(profit/total_stake * 100, 2)
    }

# Add these global variables
monitoring_task = None

# Add this at the top with other constants
ALERT_CACHE_DURATION = 3600  # 1 hour in seconds

# Function to safely check alert time
def should_send_alert(alert_text):
    current_time = time.time()
    
    try:
        if alert_text not in last_alert_time:
            return True
            
        last_time = last_alert_time[alert_text]
        # Handle if last_time is a datetime object
        if isinstance(last_time, datetime):
            last_time = last_time.timestamp()
            
        # Now both are timestamps (floats)
        time_diff = current_time - last_time
        return time_diff > 3600  # 1 hour in seconds
    except Exception as e:
        logging.error(f"Error checking alert time: {e}")
        # If there's any error in comparison, allow sending the alert
        return True

async def monitor_arbitrage_opportunities(context: ContextTypes.DEFAULT_TYPE):
    """Continuously monitor for arbitrage opportunities"""
    last_cleanup_time = time.time()
    
    while True:
        try:
            # Periodically clean up caches (every 5 minutes)
            current_time = time.time()
            if current_time - last_cleanup_time > 300:  # 5 minutes
                logging.info("Running manual cache cleanup")
                await cleanup_caches(context)
                last_cleanup_time = current_time
            
            for admin_id in ADMIN_USER_IDS:
                try:
                    # Create a proper User object
                    dummy_user = User(
                        id=admin_id,
                        is_bot=False,
                        first_name="Admin"
                    )
                    
                    # Create a proper Chat object
                    dummy_chat = Chat(
                        id=admin_id,
                        type="private"
                    )
                    
                    # Create a proper Message object
                    dummy_message = Message(
                        message_id=0,
                        date=datetime.now(),
                        chat=dummy_chat,
                        from_user=dummy_user
                    )
                    
                    # Create a proper Update object
                    dummy_update = Update(
                        update_id=0,
                        message=dummy_message
                    )
                    
                    alert = await fetch_arbitrage_opportunity(dummy_update)
                    if alert and should_send_alert(alert):
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"{alert}\n\n_{BRANDING}_",
                            parse_mode="Markdown"
                        )
                        last_alert_time[alert] = time.time()  # Always store as timestamp
                    
                    # Sleep between checks to avoid rate limits
                    await asyncio.sleep(2)
                except Exception as e:
                    logging.error(f"Error processing admin {admin_id}: {e}")
                    continue
            
            # Sleep between full cycles
            await asyncio.sleep(10)
            
        except Exception as e:
            logging.error(f"Error in monitoring task: {e}")
            await asyncio.sleep(10)

async def refresh_arbitrage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh the odds for a specific arbitrage opportunity"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in last_arb_match:
        await query.message.edit_text(f"⚠️ No previous arbitrage found to refresh.\n\n_{BRANDING}_", parse_mode="Markdown")
        return
    
    match_data = last_arb_match[user_id]
    await query.message.edit_text(f"🔄 Refreshing odds...\n\n_{BRANDING}_", parse_mode="Markdown")
    
    # Create a dummy update for the user
    dummy_user = User(
        id=user_id,
        is_bot=False,
        first_name="User"
    )
    
    dummy_chat = Chat(
        id=user_id,
        type="private"
    )
    
    dummy_message = Message(
        message_id=0,
        date=datetime.now(),
        chat=dummy_chat,
        from_user=dummy_user
    )
    
    dummy_update = Update(
        update_id=0,
        message=dummy_message
    )
    
    # Fetch fresh odds
    async with aiohttp.ClientSession() as session:
        odds_data = await fetch_odds(session, match_data["sport"], match_data["market"])
        if not odds_data:
            await query.message.edit_text(f"⚠️ Could not fetch updated odds. Please try again later.\n\n_{BRANDING}_", parse_mode="Markdown")
            return
        
        # Find the same match
        for match in odds_data:
            if (match["home_team"] == match_data["home_team"] and 
                match["away_team"] == match_data["away_team"]):
                
                # Process the match with the same parameters
                user_setting = user_settings.get(user_id, {})
                stake_amount = user_setting.get("stake_amount", 1000)
                threshold = user_setting.get("threshold", 0.5)
                selected_bookies = user_setting.get("bookies", DEFAULT_BOOKIES)
                
                result = await process_match(match, match_data["market"], selected_bookies, stake_amount, threshold)
                if result:
                    alert, new_match_data = result
                    last_arb_match[user_id] = new_match_data
                    keyboard = [
                        [InlineKeyboardButton("🔄 Refresh Odds", callback_data='refresh_arb')],
                        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back')]
                    ]
                    await query.message.edit_text(
                        f"{alert}\n\n_{BRANDING}_",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                else:
                    await query.message.edit_text(f"⚠️ Arbitrage opportunity no longer available.\n\n_{BRANDING}_", parse_mode="Markdown")
                return
        
        await query.message.edit_text(f"⚠️ Match not found in current odds.\n\n_{BRANDING}_", parse_mode="Markdown")

# Add proper cleanup for tasks
async def cleanup_tasks():
    """Cleanup all running tasks"""
    global monitoring_task
    if monitoring_task and not monitoring_task.done():
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
    monitoring_task = None

# ✅ MAIN
def main():
    logging.info("Initializing bot application")
    
    # Initialize the Application with the token
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .job_queue(None)  # Explicitly disable job queue
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stake_amount))
    
    # Add conversation handler for settings
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING: [CallbackQueryHandler(button_callback)],
            BOOKIES: [CallbackQueryHandler(button_callback)],
            THRESHOLD: [CallbackQueryHandler(button_callback)],
            STAKE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stake_amount)],
            AUTO_REFRESH: [CallbackQueryHandler(button_callback)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(conv_handler)
    
    # Start the monitoring task
    global monitoring_task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    monitoring_task = loop.create_task(monitor_arbitrage_opportunities(application))
    
    # We'll handle cache cleanup manually instead of using job_queue
    logging.warning("JobQueue disabled, cache cleanup will be handled manually")
    
    # Start the bot
    logging.info("Starting bot polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(cleanup_tasks())
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(cleanup_tasks())
        raise
