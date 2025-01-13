from telethon import TelegramClient, events, functions, types
import asyncio
import os
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage, Channel, Chat
from datetime import datetime, timedelta
import logging
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, ChannelPrivateError
import aiohttp
import mimetypes
import html
import json
import re
from collections import defaultdict
import sys
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Configure logging with more detailed format and UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('bot_logs.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # Use sys.stdout for UTF-8 support
    ]
)
logger = logging.getLogger(__name__)

# Telegram API credentials
API_ID = 'telegram api id'  
API_HASH = 'api hash  4'
BOT_TOKEN = 'bot ka token'

# Group configurations
SOURCE_GROUP = '@se  target group usernmae'  # Source telegram link username
DESTINATION_GROUP = 'output group'

# Advanced configurations
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
MEDIA_BATCH_SIZE = 10
FLOOD_SLEEP_THRESHOLD = 60  # seconds
STATS_UPDATE_INTERVAL = 1800  # 30 minutes
MESSAGE_FILTER_WORDS = []  # Add words to filter out
BACKUP_INTERVAL = 3600 * 24  # 24 hours

# Initialize thread pool
thread_pool = ThreadPoolExecutor(max_workers=4)

# Initialize clients
client = TelegramClient('user_session', API_ID, API_HASH)
bot = TelegramClient('bot_session', API_ID, API_HASH)

# Enhanced statistics tracking
message_counter = 0
media_downloads = 0
failed_forwards = 0
user_message_counts = {}
message_types_stats = defaultdict(int)
hourly_activity = defaultdict(int)
user_engagement = defaultdict(lambda: {'messages': 0, 'media': 0, 'reactions': 0})

async def login():
    """Handle user authentication"""
    global client, bot
    try:
        # Initialize clients only when needed
        if not client.is_connected():
            await client.connect()
            
        if not await client.is_user_authorized():
            print("Please login to Telegram")
            phone = input("Enter your phone number (with country code): ")
            code = await client.send_code_request(phone)
            try:
                await client.sign_in(phone, input('Enter the code you received: '))
            except:
                await client.sign_in(password=input('Enter your 2FA password: '))
                
        await bot.start(bot_token=BOT_TOKEN)
                
        logger.info("Successfully logged in!")
        return True
        
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        return False

async def resolve_source_group(source):
    """Resolve source group from various formats (username, invite link, or ID)"""
    try:
        # First check if client is connected and logged in
        if not await login():
            return None
            
        if isinstance(source, (int, str)) and str(source).startswith('-100'):
            return int(source)
            
        if source.startswith('https://t.me/'):
            invite_hash = source.split('/')[-1]
            try:
                # Try to join private group with invite link
                await client(functions.messages.ImportChatInviteRequest(invite_hash))
                # Get the channel after joining
                result = await client(functions.channels.GetChannelsRequest([source]))
                return result.chats[0].id
            except Exception as e:
                logger.error(f"Failed to join group via invite link: {e}")
                
        # Try to resolve username
        try:
            result = await client(functions.contacts.ResolveUsernameRequest(source.replace('@', '')))
            if isinstance(result.peer, (types.PeerChannel, types.PeerChat)):
                return result.peer.channel_id if isinstance(result.peer, types.PeerChannel) else result.peer.chat_id
        except Exception as e:
            logger.error(f"Failed to resolve username: {e}")
            
        # Try direct channel access
        try:
            entity = await client.get_entity(source)
            if isinstance(entity, (Channel, Chat)):
                return entity.id
        except Exception as e:
            logger.error(f"Failed to get entity: {e}")
            
    except Exception as e:
        logger.error(f"Failed to resolve source group: {e}")
        return None

async def download_media(message, download_path="downloads"):
    """Enhanced media download with retry logic and progress tracking"""
    try:
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        # Set a shorter timeout for downloads
        progress_callback = lambda current, total: logger.debug(f"Downloaded: {current}/{total} bytes")
        
        for attempt in range(MAX_RETRIES):
            try:
                # Download media with await
                file_path = await message.download_media(
                    download_path,
                    progress_callback=progress_callback
                )
                if file_path:
                    return file_path
                raise Exception("Download failed")
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                raise
                
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None

async def get_message_type(message):
    """Enhanced message type detection"""
    if message.media:
        if isinstance(message.media, MessageMediaPhoto):
            return "📸", "photo"
        elif isinstance(message.media, MessageMediaDocument):
            mime_type = message.media.document.mime_type
            if 'video' in mime_type:
                return "🎥", "video"
            elif 'audio' in mime_type:
                return "🎵", "audio" 
            elif 'gif' in mime_type:
                return "🎭", "gif"
            elif 'image' in mime_type:
                return "🖼", "image"
            elif 'pdf' in mime_type:
                return "📑", "pdf"
            elif 'zip' in mime_type or 'rar' in mime_type:
                return "🗜", "archive"
            return "📎", "document"
        elif isinstance(message.media, MessageMediaWebPage):
            return "🔗", "webpage"
    elif message.poll:
        return "📊", "poll"
    elif message.voice:
        return "🎤", "voice"
    elif message.video_note:
        return "🎦", "video_note"
    elif message.sticker:
        return "🎯", "sticker"
    return "💬", "text"

async def get_sender_info(message):
    """Enhanced sender information collection"""
    try:
        sender = await message.get_sender()
        sender_id = sender.id
        username = sender.username if sender.username else "No Username"
        first_name = html.escape(sender.first_name) if sender.first_name else "No Name"
        last_name = html.escape(sender.last_name) if sender.last_name else ""
        full_name = f"{first_name} {last_name}".strip()
        
        # Get additional user info
        user_info = {
            'id': sender_id,
            'username': username,
            'name': full_name,
            'premium': getattr(sender, 'premium', False),
            'bot': getattr(sender, 'bot', False),
            'verified': getattr(sender, 'verified', False),
            'phone': getattr(sender, 'phone', None),
            'last_seen': None
        }
        
        try:
            full_user = await client(functions.users.GetFullUserRequest(id=sender_id))
            user_info['about'] = getattr(full_user.about, 'about', None)
            user_info['common_chats_count'] = full_user.common_chats_count
        except Exception:
            pass
            
        return user_info
        
    except Exception as e:
        logger.error(f"Error getting sender info: {e}")
        return {
            'id': 0,
            'username': 'unknown',
            'name': 'Unknown User'
        }

async def forward_message(message, destination):
    """Enhanced message forwarding with advanced features"""
    try:
        emoji, msg_type = await get_message_type(message)
        sender_info = await get_sender_info(message)
        
        # Update statistics
        user_id = sender_info['id']
        user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
        message_types_stats[msg_type] += 1
        hour = datetime.now().hour
        hourly_activity[hour] += 1
        
        # Enhanced header with more information
        header = f"👤 From: {sender_info['name']} (@{sender_info['username']})\n"
        header += f"💌 Message Count: {user_message_counts[user_id]}\n"
        header += f"🕒 Sent at: {message.date.strftime('%Y-%m-%d %H:%M:%S')}\n"
        if sender_info['premium']:
            header += "⭐ Premium User\n"
        if message.forward:
            header += f"↪️ Forwarded from: {message.forward.sender.first_name if message.forward.sender else 'Unknown'}\n"
        header += f"📝 Message Type: {msg_type}\n\n"

        # Handle polls
        if message.poll:
            poll = message.poll
            poll_text = f"{header}📊 Poll: {poll.question}\n\nOptions:\n"
            for option in poll.options:
                poll_text += f"- {option.text}\n"
            await bot.send_message(destination, poll_text)
            return True
        
        # Handle media messages with enhanced features
        if message.media and not isinstance(message.media, MessageMediaWebPage):
            file_path = await download_media(message)
            if file_path:
                global media_downloads
                media_downloads += 1
                user_engagement[user_id]['media'] += 1
                
                caption = header
                if message.text:
                    caption += message.text
                
                # Get media info
                file_size = os.path.getsize(file_path)
                mime_type = mimetypes.guess_type(file_path)[0]
                
                # Add media info to caption
                caption += f"\n\n📊 File Info:\n"
                caption += f"📦 Size: {file_size/1024/1024:.2f} MB\n"
                caption += f"🏷 Type: {mime_type}\n"

                # Always send videos as videos, not as documents
                if 'video' in mime_type:
                    await bot.send_file(
                        destination,
                        file_path,
                        caption=caption,
                        reply_to=message.reply_to_msg_id if message.reply_to_msg_id else None,
                        supports_streaming=True,
                        force_document=False  # Always send as video
                    )
                else:
                    await bot.send_file(
                        destination,
                        file_path,
                        caption=caption,
                        reply_to=message.reply_to_msg_id if message.reply_to_msg_id else None,
                        supports_streaming=True if 'video' in mime_type else None
                    )
                
                os.remove(file_path)
                logger.info(f"Successfully forwarded {msg_type} with media from {sender_info['name']}")
                return True
            return False
            
        # Handle text messages with enhanced formatting
        else:
            text = header
            if message.text:
                # Add formatting for links and mentions
                text += message.text
                
                # Extract and display URLs
                urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message.text)
                if urls:
                    text += "\n\n🔗 Links found:\n"
                    for url in urls:
                        text += f"• {url}\n"
            else:
                text += "Empty message"
                
            await bot.send_message(
                destination,
                text,
                reply_to=message.reply_to_msg_id if message.reply_to_msg_id else None,
                link_preview=True
            )
            logger.info(f"Successfully forwarded text message from {sender_info['name']}")
            return True
            
    except FloodWaitError as e:
        logger.warning(f"Hit rate limit. Waiting {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        return await forward_message(message, destination)
        
    except Exception as e:
        logger.error(f"Error forwarding message: {str(e)}")
        global failed_forwards
        failed_forwards += 1
        return False

@client.on(events.NewMessage(chats=SOURCE_GROUP))
async def handle_new_message(event):
    """Enhanced message handler with filtering and rate limiting"""
    try:
        # Check for filtered words
        if MESSAGE_FILTER_WORDS and any(word in event.text.lower() for word in MESSAGE_FILTER_WORDS):
            logger.info("Message filtered due to containing filtered words")
            return
            
        global message_counter
        success = await forward_message(event.message, DESTINATION_GROUP)
        
        if success:
            message_counter += 1
            emoji, msg_type = await get_message_type(event.message)
            sender_info = await get_sender_info(event.message)
            
            # Update engagement metrics
            user_id = sender_info['id']
            user_engagement[user_id]['messages'] += 1
            
            logger.info(f"Forwarded {msg_type} message from {sender_info['name']} ({message_counter} messages processed)")
            
        # Implement rate limiting
        await asyncio.sleep(1)
        
    except Exception as e:
        logger.error(f"Error processing new message: {str(e)}")

async def status_monitor():
    """Enhanced status monitoring with detailed statistics"""
    try:
        while True:
            # Get top 5 most active users
            top_users = sorted(user_message_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            top_users_text = "\n".join([f"👤 User {uid}: {count} messages" for uid, count in top_users])
            
            # Calculate message type distribution
            type_distribution = "\n".join([f"{type_}: {count}" for type_, count in message_types_stats.items()])
            
            # Calculate peak hours
            if hourly_activity:  # Check if hourly_activity is not empty
                peak_hour = max(hourly_activity.items(), key=lambda x: x[1])[0]
                peak_hour_text = f"⏰ Peak Activity Hour: {peak_hour}:00\n\n"
            else:
                peak_hour_text = ""
            
            status = (
                f"📊 Advanced Bot Status Report\n"
                f"✅ Messages Processed: {message_counter}\n"
                f"📥 Media Downloads: {media_downloads}\n"
                f"❌ Failed Forwards: {failed_forwards}\n"
                f"🕒 Running Since: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📱 Source: {SOURCE_GROUP}\n"
                f"📲 Destination: {DESTINATION_GROUP}\n\n"
                f"📊 Message Types:\n{type_distribution}\n\n"
                f"{peak_hour_text}"
                f"🏆 Top 5 Active Users:\n{top_users_text}"
            )
            
            await bot.send_message(DESTINATION_GROUP, status)
            
            # Backup statistics to JSON
            if message_counter % 100 == 0:  # Backup every 100 messages
                await backup_statistics()
                
            await asyncio.sleep(STATS_UPDATE_INTERVAL)
            
    except Exception as e:
        logger.error(f"Status monitor error: {str(e)}")

async def backup_statistics():
    """Backup statistics to JSON file"""
    stats = {
        'message_counter': message_counter,
        'media_downloads': media_downloads,
        'failed_forwards': failed_forwards,
        'user_message_counts': user_message_counts,
        'message_types_stats': dict(message_types_stats),
        'hourly_activity': dict(hourly_activity),
        'user_engagement': {str(k): v for k, v in user_engagement.items()}
    }
    
    with open('bot_stats_backup.json', 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

async def main():
    """Enhanced main function with initialization and cleanup"""
    try:
        # Login first
        if not await login():
            logger.error("Failed to login")
            return
            
        # Resolve source group
        source_id = await resolve_source_group(SOURCE_GROUP)
        if not source_id:
            logger.error("Failed to resolve source group")
            return
            
        # Start status monitor in a separate task
        asyncio.create_task(status_monitor())
        
        # Run until disconnected
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        raise
    finally:
        # Backup statistics before exit
        await backup_statistics()
        if client:
            await client.disconnect()
        if bot:
            await bot.disconnect()

if __name__ == '__main__':
    # Run the client
    asyncio.run(main())
