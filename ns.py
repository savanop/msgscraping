from telethon import TelegramClient, events
import asyncio
import os
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from datetime import datetime
import logging
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, ChatWriteForbiddenError
import aiohttp
import mimetypes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_logs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Telegram API credentials
API_ID = '22862061'  
API_HASH = '5209af9bad0be1f663d657ad05ddfce4'
BOT_TOKEN = '7866801642:AAE_G3sletfutnqUO2MpdH1nXa09SXwi79k'

# Group configurations
SOURCE_GROUP = 'savangroup1'
DESTINATION_GROUP = 'hxhd72'

# Initialize client with user session instead of bot token
client = TelegramClient('user_session', API_ID, API_HASH)

# Message counter and stats
message_counter = 0
media_downloads = 0
failed_forwards = 0

async def download_media(message, download_path="downloads"):
    """Download media from message"""
    try:
        if not os.path.exists(download_path):
            os.makedirs(download_path)
            
        file_path = await message.download_media(download_path)
        return file_path
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None

async def get_message_type(message):
    """Determine message type and return appropriate emoji and type"""
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
            return "📎", "document"
        elif isinstance(message.media, MessageMediaWebPage):
            return "🔗", "webpage"
    return "💬", "text"

async def forward_message(message, destination):
    """Forward message with advanced error handling"""
    try:
        # Get message type
        emoji, msg_type = await get_message_type(message)
        
        # Handle media messages
        if message.media and not isinstance(message.media, MessageMediaWebPage):
            # Download media first
            file_path = await download_media(message)
            if file_path:
                global media_downloads
                media_downloads += 1
                
                # Send downloaded media
                await client.send_file(
                    destination,
                    file_path,
                    caption=message.text if message.text else None,
                    reply_to=message.reply_to_msg_id if message.reply_to_msg_id else None
                )
                
                # Cleanup downloaded file
                os.remove(file_path)
                logger.info(f"Successfully forwarded {msg_type} with media")
                return True
            return False
            
        # Handle text messages
        else:
            await client.send_message(
                destination,
                message.text or "Empty message",
                reply_to=message.reply_to_msg_id if message.reply_to_msg_id else None
            )
            logger.info(f"Successfully forwarded text message")
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
    """Handle new messages as they arrive"""
    try:
        global message_counter
        success = await forward_message(event.message, DESTINATION_GROUP)
        
        if success:
            message_counter += 1
            emoji, msg_type = await get_message_type(event.message)
            logger.info(f"Forwarded {msg_type} message ({message_counter} messages processed)")
            
        await asyncio.sleep(1)
        
    except Exception as e:
        logger.error(f"Error processing new message: {str(e)}")

async def status_monitor():
    """Monitor and report bot status"""
    while True:
        try:
            status = (
                f"📊 Bot Status Report\n"
                f"✅ Messages Processed: {message_counter}\n"
                f"📥 Media Downloads: {media_downloads}\n"
                f"❌ Failed Forwards: {failed_forwards}\n"
                f"🕒 Running Since: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📱 Source: {SOURCE_GROUP}\n"
                f"📲 Destination: {DESTINATION_GROUP}"
            )
            await client.send_message(DESTINATION_GROUP, status)
            await asyncio.sleep(3600)  # Update every hour
            
        except Exception as e:
            logger.error(f"Status monitor error: {str(e)}")
            await asyncio.sleep(300)

async def main():
    """Main function to run the bot"""
    try:
        # Start client as user instead of bot
        await client.start()
        logger.info("User client started successfully!")
        
        # Start status monitoring
        asyncio.create_task(status_monitor())
        
        # Run until disconnected
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        raise

if __name__ == '__main__':
    # Run the client
    asyncio.run(main())
