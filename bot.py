
import os
import time
import asyncio
import math
from datetime import datetime as dt
import glob
import shutil
import json
import subprocess
from os import getenv
from dotenv import load_dotenv

from telethon import TelegramClient, events, Button
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from telethon.tl.types import DocumentAttributeVideo
from telethon.utils import get_display_name

# Load environment variables
load_dotenv()

# Initialize the bot
API_ID = int(getenv("API_ID", "24955235"))
API_HASH = getenv("API_HASH", "f317b3f7bbe390346d8b46868cff0de8")
BOT_TOKEN = getenv("BOT_TOKEN", "7560987376:AAFNJmERp1WT3WgBwkaKV6lqjPxUZ5ZKzak")
BOT_UN = getenv("BOT_UN", "NGTrimmerBot")

# Support and info
SUPPORT_LINK = getenv("SUPPORT_LINK", "https://t.me/your_support_channel")
THUMBNAIL_PATH = "thumbnails/trim_thumb.jpg"

# Ensure directories exist
os.makedirs("downloads", exist_ok=True)
os.makedirs("processed", exist_ok=True)
os.makedirs("thumbnails", exist_ok=True)

# Create a default thumbnail if it doesn't exist
if not os.path.exists(THUMBNAIL_PATH):
    try:
        os.makedirs(os.path.dirname(THUMBNAIL_PATH), exist_ok=True)
        with open(THUMBNAIL_PATH, "w") as f:
            f.write("")  # Create empty file for now, replace with actual thumbnail
    except Exception as e:
        print(f"Error creating thumbnail file: {e}")
        THUMBNAIL_PATH = None

# Create the client
bot = TelegramClient('VideoTrimmerBot', API_ID, API_HASH)

# User state storage
user_states = {}

class UserState:
    def __init__(self):
        self.file_path = None
        self.start_time = None
        self.end_time = None
        self.file_name = None
        self.original_message = None
        self.progress_message = None
        self.last_update_time = 0


async def progress_bar(current, total, message, start_time, text="**PROGRESS:**"):
    """Show a progress bar with percentage and speed"""
    now = time.time()
    elapsed_time = now - start_time
    if current == total or (now - message.state.last_update_time) > 2:  # Update every 2 seconds
        message.state.last_update_time = now
        percentage = current * 100 / total
        speed = current / elapsed_time if elapsed_time > 0 else 0
        speed_string = f"{humanbytes(speed)}/s"
        
        progress = min(int(percentage / 5), 20)  # 20 chars max
        progress_bar_str = '▰' * progress + '▱' * (20 - progress)
        
        time_remaining = (total - current) / speed if speed > 0 else 0
        time_str = time_formatter(time_remaining)
        
        try:
            await message.edit(
                f"{text}\n"
                f"╞═{progress_bar_str}╡ {percentage:.2f}%\n"
                f"**Size:** {humanbytes(current)} / {humanbytes(total)}\n"
                f"**Speed:** {speed_string}\n"
                f"**ETA:** {time_str}"
            )
        except MessageNotModifiedError:
            pass


def humanbytes(size):
    """Convert bytes to human readable format"""
    if not size:
        return "0 B"
    power = 2**10  # 1024
    n = 0
    units = {0: "B", 1: "KB", 2: "MB", 3: "GB", 4: "TB"}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"


def time_formatter(seconds):
    """Format seconds into readable time string"""
    if seconds <= 0:
        return "0s"
    
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


async def fast_download(file_path, message, client, progress_message):
    """Download file with progress updates"""
    progress_message.state = UserState()
    progress_message.state.last_update_time = time.time()
    
    start_time = time.time()
    
    try:
        downloaded_file = await client.download_media(
            message=message,
            file=file_path,
            progress_callback=lambda current, total: asyncio.create_task(
                progress_bar(current, total, progress_message, start_time, "**DOWNLOADING:**")
            )
        )
        return downloaded_file
    except Exception as e:
        print(f"Download error: {e}")
        raise e


async def fast_upload(file_path, client, progress_message, caption):
    """Upload file with progress updates"""
    progress_message.state = UserState()
    progress_message.state.last_update_time = time.time()
    
    start_time = time.time()
    file_name = os.path.basename(file_path)
    
    try:
        if file_path.endswith(('.mp4', '.mkv', '.webm', '.avi')):
            # Get video metadata
            metadata = await get_video_metadata(file_path)
            width = metadata.get("width", 0)
            height = metadata.get("height", 0)
            duration = metadata.get("duration", 0)
            
            # For video files
            uploaded_file = await client.send_file(
                progress_message.chat_id,
                file=file_path,
                caption=caption,
                supports_streaming=True,
                thumb=THUMBNAIL_PATH if THUMBNAIL_PATH and os.path.exists(THUMBNAIL_PATH) and os.path.getsize(THUMBNAIL_PATH) > 0 else None,
                attributes=[DocumentAttributeVideo(
                    duration=int(duration),
                    w=width,
                    h=height,
                    supports_streaming=True
                )],
                progress_callback=lambda current, total: asyncio.create_task(
                    progress_bar(current, total, progress_message, start_time, "**UPLOADING:**")
                )
            )
        else:
            # For non-video files
            uploaded_file = await client.send_file(
                progress_message.chat_id,
                file=file_path,
                caption=caption,
                thumb=THUMBNAIL_PATH if THUMBNAIL_PATH and os.path.exists(THUMBNAIL_PATH) and os.path.getsize(THUMBNAIL_PATH) > 0 else None,
                force_document=True,
                progress_callback=lambda current, total: asyncio.create_task(
                    progress_bar(current, total, progress_message, start_time, "**UPLOADING:**")
                )
            )
        return uploaded_file
    except Exception as e:
        print(f"Upload error: {e}")
        raise e


async def get_video_metadata(file_path):
    """Get video metadata using ffprobe"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json", 
            "-show_format", "-show_streams", file_path
        ]
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()
        
        if process.returncode != 0:
            print(f"Error getting metadata: {error.decode()}")
            return {"width": 0, "height": 0, "duration": 0}
        
        metadata = json.loads(output.decode())
        
        # Find video stream
        video_stream = None
        for stream in metadata.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if not video_stream:
            return {"width": 0, "height": 0, "duration": 0}
        
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        
        # Get duration
        duration = float(video_stream.get("duration", 0))
        if duration == 0:
            duration = float(metadata.get("format", {}).get("duration", 0))
        
        return {
            "width": width,
            "height": height,
            "duration": duration
        }
    except Exception as e:
        print(f"Error in get_video_metadata: {e}")
        return {"width": 0, "height": 0, "duration": 0}


async def execute_ffmpeg(input_file, output_file, start_time, end_time):
    """Execute ffmpeg command to trim video"""
    try:
        # Make sure ffmpeg is installed and in PATH
        if not shutil.which("ffmpeg"):
            print("FFmpeg not found! Please install FFmpeg and make sure it's in your PATH.")
            raise Exception("FFmpeg not installed or not in PATH")
        
        # Check if input file exists
        if not os.path.exists(input_file):
            print(f"Input file does not exist: {input_file}")
            raise Exception(f"Input file not found: {input_file}")
            
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Create ffmpeg command
        cmd = [
            "ffmpeg", "-i", input_file, "-ss", start_time, 
            "-to", end_time, "-c:v", "copy", "-c:a", "copy", 
            "-avoid_negative_ts", "make_zero", output_file, 
            "-y"
        ]
        
        print(f"Executing FFmpeg command: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode() if stderr else 'Unknown error'}")
            raise Exception(f"FFmpeg failed with code {process.returncode}")
        
        # Verify output file was created
        if not os.path.exists(output_file):
            print(f"Output file was not created: {output_file}")
            raise Exception("Output file was not created")
            
        return output_file
    except Exception as e:
        print(f"Error in execute_ffmpeg: {e}")
        raise e


# New function for splitting a video into segments
async def split_video_into_segments(input_file, output_pattern, segment_duration):
    """Split video into segments of equal duration using ffmpeg"""
    try:
        # Make sure ffmpeg is installed
        if not shutil.which("ffmpeg"):
            print("FFmpeg not found! Please install FFmpeg and make sure it's in your PATH.")
            raise Exception("FFmpeg not installed or not in PATH")
        
        # Check if input file exists
        if not os.path.exists(input_file):
            print(f"Input file does not exist: {input_file}")
            raise Exception(f"Input file not found: {input_file}")
            
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_pattern), exist_ok=True)
        
        # Create ffmpeg command for segmenting
        cmd = [
            "ffmpeg", "-i", input_file, 
            "-c", "copy", "-map", "0",
            "-segment_time", str(segment_duration), 
            "-f", "segment", "-reset_timestamps", "1",
            output_pattern, "-y"
        ]
        
        print(f"Executing FFmpeg segment command: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg segment error: {stderr.decode() if stderr else 'Unknown error'}")
            raise Exception(f"FFmpeg segmentation failed with code {process.returncode}")
            
        # List of generated segment files
        segment_files = sorted(glob.glob(output_pattern.replace("%03d", "*")))
        
        if not segment_files:
            print(f"No segment files were created with pattern: {output_pattern}")
            raise Exception("No segment files were created")
            
        return segment_files
    except Exception as e:
        print(f"Error in split_video_into_segments: {e}")
        raise e


# Bot event handlers
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Handle /start command"""
    user = await event.get_sender()
    username = get_display_name(user)
    
    welcome_text = (
        f"👋 Hello {username}!\n\n"
        f"I'm **Video Trimmer Pro Bot** - I can help you trim your videos easily.\n\n"
        f"Just send me a video file, and I'll guide you through the trimming process.\n\n"
        f"**Features:**\n"
        f"• Trim videos to specific time segments\n"
        f"• Split videos into 1-minute parts\n"
        f"• Maintains original video quality\n"
        f"• Supports multiple video formats\n"
        f"• Real-time progress updates\n\n"
        f"Send a video to get started!"
    )
    
    # Fixed: Using only inline buttons
    buttons = [
        [Button.url("Support Channel", SUPPORT_LINK)],
        [Button.inline("How to use", b"how_to_use")]
    ]
    
    await event.respond(welcome_text, buttons=buttons)


@bot.on(events.CallbackQuery(data=b"how_to_use"))
async def how_to_use_handler(event):
    """Handle how to use button click"""
    instructions = (
        "**How to Use Video Trimmer Bot:**\n\n"
        "1. Send any video file to the bot\n"
        "2. Choose an operation mode:\n"
        "   • **Trim Mode:** Trim video between specific times\n"
        "   • **Split Mode:** Split video into 1-minute segments\n\n"
        "**For Trim Mode:**\n"
        "Enter the start and end times in format: `mm:ss` or `hh:mm:ss`\n"
        "Example: `00:30 02:15`\n\n"
        "**For Split Mode:**\n"
        "The bot will automatically split your video into 1-minute segments and send them to you."
    )
    
    await event.answer()
    await event.respond(instructions)


@bot.on(events.NewMessage(func=lambda e: e.media))
async def media_handler(event):
    """Handle incoming media files"""
    user_id = event.sender_id
    
    # Check if media is video
    if hasattr(event.media, "document"):
        mime_type = event.media.document.mime_type
        is_video = mime_type and ("video" in mime_type)
    else:
        is_video = bool(event.video)
    
    if not is_video:
        await event.respond("Please send a video file to trim or split.")
        return
    
    # Initialize user state
    if user_id not in user_states:
        user_states[user_id] = UserState()
    
    user_states[user_id].original_message = event.message
    
    # Get video duration
    duration = 0
    if hasattr(event.media, "document") and hasattr(event.media.document, "attributes"):
        for attr in event.media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                duration = attr.duration
                break
    
    # Format duration
    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
    
    # Create buttons for operation mode
    buttons = [
        [
            Button.inline("✂️ Trim Video", b"mode_trim"),
            Button.inline("🪓 Split into 1-Min Parts", b"mode_split")
        ]
    ]
    
    instructions = (
        f"**Video received!**\n\n"
        f"Video duration: `{duration_str}`\n\n"
        f"Please select what you want to do with this video:"
    )
    
    await event.respond(instructions, buttons=buttons)


@bot.on(events.CallbackQuery(data=b"mode_trim"))
async def trim_mode_handler(event):
    """Handle selection of trim mode"""
    user_id = event.sender_id
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.answer("Please send a video first!", alert=True)
        return
    
    # Get video duration
    duration = 0
    original_message = user_states[user_id].original_message
    if hasattr(original_message.media, "document") and hasattr(original_message.media.document, "attributes"):
        for attr in original_message.media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                duration = attr.duration
                break
    
    # Format duration
    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
    
    instructions = (
        f"**✂️ TRIM MODE Selected**\n\n"
        f"Video duration: `{duration_str}`\n\n"
        f"Please reply with start and end times in format:\n"
        f"`start_time end_time`\n\n"
        f"Example: `00:30 02:15`\n"
        f"(This trims from 30 seconds to 2 minutes 15 seconds)"
    )
    
    await event.answer()
    await event.edit(instructions)


@bot.on(events.CallbackQuery(data=b"mode_split"))
async def split_mode_handler(event):
    """Handle selection of split mode with options"""
    user_id = event.sender_id
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.answer("Please send a video first!", alert=True)
        return
    
    await event.answer()
    
    # Offer different splitting options
    split_options = (
        "**🪓 SPLIT MODE Selected**\n\n"
        "Choose how you'd like to split your video:"
    )
    
    buttons = [
        [Button.inline("1-Minute Segments (Default)", b"confirm_split")],
        [Button.inline("Custom Duration Segments", b"custom_split")],
        [Button.inline("❌ Cancel", b"cancel_split")]
    ]
    
    await event.edit(split_options, buttons=buttons)


@bot.on(events.CallbackQuery(data=b"confirm_split"))
async def confirm_split_handler(event):
    """Handle confirmation of split operation"""
    user_id = event.sender_id
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.answer("Please send a video first!", alert=True)
        return
    
    await event.answer("Starting split operation...")
    
    # Update message to show progress
    progress_message = await event.edit("**Initializing split operation...**")
    
    # Start the splitting process
    await split_video(progress_message, user_states[user_id].original_message)


@bot.on(events.CallbackQuery(data=b"cancel_split"))
async def cancel_split_handler(event):
    """Handle cancellation of split operation"""
    await event.answer("Operation cancelled.")
    
    await event.edit(
        "**Operation cancelled.**\n\n"
        "Send another video or use /start to restart."
    )


@bot.on(events.CallbackQuery(data=b"custom_split"))
async def custom_split_handler(event):
    """Handle request for custom split duration"""
    user_id = event.sender_id
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.answer("Please send a video first!", alert=True)
        return
    
    await event.answer()
    
    instructions = (
        "**🪓 CUSTOM SPLIT DURATION**\n\n"
        "Please enter the duration (in seconds) for each segment.\n\n"
        "Example: Enter `120` for 2-minute segments.\n\n"
        "Recommended values: 30-300 seconds."
    )
    
    await event.edit(instructions)
    
    # Update user state to indicate waiting for custom duration
    user_states[user_id].waiting_for_custom_duration = True


@bot.on(events.NewMessage(func=lambda e: not e.media and e.text.isdigit()))
async def custom_duration_handler(event):
    """Handle custom duration input for video splitting"""
    user_id = event.sender_id
    
    # Check if user has an active video and is waiting for custom duration
    if (user_id not in user_states or 
        not user_states[user_id].original_message or 
        not getattr(user_states[user_id], 'waiting_for_custom_duration', False)):
        return
    
    # Get the duration in seconds
    try:
        duration = int(event.text.strip())
        
        if duration < 5 or duration > 600:
            await event.respond(
                "⚠️ **Invalid duration!**\n\n"
                "Please enter a value between 5 and 600 seconds."
            )
            return
        
        # Reset the waiting state
        user_states[user_id].waiting_for_custom_duration = False
        
        # Start the custom splitting process
        progress_message = await event.respond(f"**Starting split with {duration} second segments...**")
        await split_video_custom_duration(progress_message, user_states[user_id].original_message, duration)
    except ValueError:
        await event.respond("Please enter a valid number of seconds.")


@bot.on(events.NewMessage(func=lambda e: not e.media and not e.text.startswith('/')))
async def trim_command_handler(event):
    """Handle trim time inputs"""
    user_id = event.sender_id
    text = event.text.strip()
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.respond("Please send a video first!")
        return
    
    # Try to parse start and end times
    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Invalid format")
        
        start_time = parts[0]
        end_time = parts[1]
        
        # Validate time format
        for time_str in (start_time, end_time):
            if ":" not in time_str:
                raise ValueError("Invalid time format")
            
            time_parts = time_str.split(":")
            if len(time_parts) not in (2, 3):
                raise ValueError("Invalid time format")
            
            for part in time_parts:
                if not part.isdigit():
                    raise ValueError("Time must contain only digits")
        
        # Start trimming process
        await trim_video(event, user_states[user_id].original_message, start_time, end_time)
    except ValueError as e:
        await event.respond(
            f"❌ **Error:** {str(e)}\n\n"
            f"Please use the format: `start_time end_time`\n"
            f"Example: `00:30 02:15`"
        )


async def trim_video(event, original_message, start_time, end_time):
    """Process video trimming"""
    user_id = event.sender_id
    
    # Create unique filenames
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    input_file = os.path.abspath(f"downloads/input_{user_id}_{timestamp}")
    output_file = os.path.abspath(f"processed/trimmed_{user_id}_{timestamp}")
    
    # Determine file extension
    if hasattr(original_message.media, "document"):
        mime_type = original_message.media.document.mime_type
        if "mp4" in mime_type:
            input_file += ".mp4"
            output_file += ".mp4"
        elif "x-matroska" in mime_type:
            input_file += ".mkv"
            output_file += ".mkv"
        elif "webm" in mime_type:
            input_file += ".webm"
            output_file += ".webm"
        else:
            # Try to get the file extension from the name
            if hasattr(original_message.media.document, "attributes"):
                for attr in original_message.media.document.attributes:
                    if hasattr(attr, "file_name") and attr.file_name:
                        if "." in attr.file_name:
                            ext = attr.file_name.split(".")[-1]
                            input_file += f".{ext}"
                            output_file += f".{ext}"
                            break
            
            # Default to mp4 if we couldn't determine the extension
            if not "." in input_file:
                input_file += ".mp4"
                output_file += ".mp4"
    else:
        input_file += ".mp4"
        output_file += ".mp4"
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(input_file), exist_ok=True)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # Send initial progress message
    progress_message = await event.respond("**Initializing video trimming...**")
    
    try:
        # Download the file with progress updates
        await progress_message.edit("**⬇️ Downloading video...**")
        downloaded_file = await fast_download(input_file, original_message, bot, progress_message)
        
        if not downloaded_file:
            await progress_message.edit("❌ **Error:** Failed to download the video.")
            return
        
        # Trim video using ffmpeg
        await progress_message.edit(f"**✂️ Trimming video...**\nFrom `{start_time}` to `{end_time}`")
        trimmed_file = await execute_ffmpeg(input_file, output_file, start_time, end_time)
        
        if not trimmed_file or not os.path.exists(trimmed_file):
            await progress_message.edit("❌ **Error:** Failed to trim the video.")
            return
        
        # Get file size
        file_size = os.path.getsize(trimmed_file)
        readable_size = humanbytes(file_size)
        
        # Upload the trimmed video with progress updates
        await progress_message.edit("**⬆️ Uploading trimmed video...**")
        
        # Prepare caption
        caption = (
            f"**🎬 Trimmed Video**\n"
            f"**Duration:** `{start_time}` to `{end_time}`\n"
            f"**Size:** {readable_size}\n\n"
            f"Trimmed by @{BOT_UN}"
        )
        
        await fast_upload(trimmed_file, bot, progress_message, caption)
        
        # Final message
        await progress_message.edit("**✅ Video trimming completed!**\nSend another video for processing.")
        
    except Exception as e:
        print(f"Error in trim_video: {e}")
        await progress_message.edit(f"❌ **Error:** {str(e)}\n\nPlease try again.")
    
    finally:
        # Clean up temporary files
        try:
            if os.path.exists(input_file):
                os.remove(input_file)
            if os.path.exists(output_file):
                os.remove(output_file)
        except Exception as cleanup_error:
            print(f"Error cleaning up files: {cleanup_error}")


async def split_video(progress_message, original_message, segment_duration=60):
    """Process video splitting into 1-minute segments"""
    user_id = original_message.sender_id
    
    # Create unique filenames
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    input_file = os.path.abspath(f"downloads/input_{user_id}_{timestamp}")
    output_pattern = os.path.abspath(f"processed/segment_{user_id}_{timestamp}_%03d")
    
    # Determine file extension
    if hasattr(original_message.media, "document"):
        mime_type = original_message.media.document.mime_type
        if "mp4" in mime_type:
            input_file += ".mp4"
            output_pattern += ".mp4"
        elif "x-matroska" in mime_type:
            input_file += ".mkv"
            output_pattern += ".mkv"
        elif "webm" in mime_type:
            input_file += ".webm"
            output_pattern += ".webm"
        else:
            # Try to get the file extension from the name
            if hasattr(original_message.media.document, "attributes"):
                for attr in original_message.media.document.attributes:
                    if hasattr(attr, "file_name") and attr.file_name:
                        if "." in attr.file_name:
                            ext = attr.file_name.split(".")[-1]
                            input_file += f".{ext}"
                            output_pattern += f".{ext}"
                            break
            
            # Default to mp4 if we couldn't determine the extension
            if not "." in input_file:
                input_file += ".mp4"
                output_pattern += ".mp4"
    else:
        input_file += ".mp4"
        output_pattern += ".mp4"
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(input_file), exist_ok=True)
    os.makedirs(os.path.dirname(output_pattern), exist_ok=True)
    
    try:
        # Download the file with progress updates
        await progress_message.edit("**⬇️ Downloading video...**")
        downloaded_file = await fast_download(input_file, original_message, bot, progress_message)
        
        if not downloaded_file:
            await progress_message.edit("❌ **Error:** Failed to download the video.")
            return
        
        # Split video using ffmpeg
        await progress_message.edit(f"**🪓 Splitting video into {segment_duration}-second segments...**")
        segment_files = await split_video_into_segments(input_file, output_pattern, segment_duration)
        
        if not segment_files:
            await progress_message.edit("❌ **Error:** Failed to split the video.")
            return
        
        # Calculate total segments
        total_segments = len(segment_files)
        
        await progress_message.edit(f"**✅ Video split into {total_segments} segments!**\n\nUploading segments...")
        
        # Upload each segment with progress
        for i, segment_file in enumerate(segment_files, 1):
            # Get file size
            file_size = os.path.getsize(segment_file)
            readable_size = humanbytes(file_size)
            
            # Prepare caption
            caption = (
                f"**🎬 Video Segment {i}/{total_segments}**\n"
                f"**Duration:** {segment_duration} seconds\n"
                f"**Size:** {readable_size}\n\n"
                f"Split by @{BOT_UN}"
            )
            
            # Update progress message
            await progress_message.edit(f"**⬆️ Uploading segment {i}/{total_segments}...**")
            
            # Upload segment
            await fast_upload(segment_file, bot, progress_message, caption)
        
        # Final message
        await progress_message.edit(
            f"**✅ All {total_segments} segments uploaded!**\n"
            f"Send another video for processing."
        )
        
    except Exception as e:
        print(f"Error in split_video: {e}")
        await progress_message.edit(f"❌ **Error:** {str(e)}\n\nPlease try again.")
    
    finally:
        # Clean up temporary files
        try:
            if os.path.exists(input_file):
                os.remove(input_file)
            
            # Clean up segment files
            for pattern in [output_pattern.replace("%03d", "*")]:
                for file in glob.glob(pattern):
                    if os.path.exists(file):
                        os.remove(file)
        except Exception as cleanup_error:
            print(f"Error cleaning up files: {cleanup_error}")


async def split_video_custom_duration(progress_message, original_message, segment_duration):
    """Process video splitting with custom duration segments"""
    # Reuse the same function but with custom duration
    await split_video(progress_message, original_message, segment_duration)


@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    """Handle /help command"""
    help_text = (
        "**📋 Video Trimmer Bot Help**\n\n"
        "**Basic Commands:**\n"
        "• `/start` - Start the bot\n"
        "• `/help` - Show this help message\n\n"
        
        "**How to Trim Videos:**\n"
        "1. Send any video file to the bot\n"
        "2. Select '✂️ Trim Video' option\n"
        "3. Reply with start and end times in format: `start_time end_time`\n"
        "   Example: `00:30 02:15`\n\n"
        
        "**How to Split Videos:**\n"
        "1. Send any video file to the bot\n"
        "2. Select '🪓 Split into Parts' option\n"
        "3. Choose between default 1-minute segments or custom duration\n"
        "4. For custom duration, input the number of seconds for each segment\n\n"
        
        "**Time Format:**\n"
        "• For short videos: `mm:ss` (minutes:seconds)\n"
        "• For longer videos: `hh:mm:ss` (hours:minutes:seconds)\n\n"
        
        "**Tips:**\n"
        "• Send videos as files for better quality\n"
        "• Maximum file size: 2GB (Telegram limit)\n"
        "• For best results, use MP4 format\n\n"
        
        "If you need further assistance, contact support."
    )
    
    buttons = [
        [Button.url("Support Channel", SUPPORT_LINK)]
    ]
    
    await event.respond(help_text, buttons=buttons)


@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    """Handle /cancel command"""
    user_id = event.sender_id
    
    if user_id in user_states:
        del user_states[user_id]
        await event.respond("**❌ All operations cancelled.**\nSend a new video to start over.")
    else:
        await event.respond("No active operations to cancel.")


@bot.on(events.NewMessage(pattern='/clean'))
async def clean_handler(event):
    """Handle /clean command - Clean up temporary files"""
    # Check if user is admin/owner
    user_id = event.sender_id
    
    # Add your admin/owner user IDs here
    admin_ids = [1234567890]  # Replace with actual admin IDs
    
    if user_id not in admin_ids:
        await event.respond("You don't have permission to use this command.")
        return
    
    # Clean up temporary directories
    try:
        # Count files
        download_files = len(glob.glob("downloads/*"))
        processed_files = len(glob.glob("processed/*"))
        total_files = download_files + processed_files
        
        # Delete files
        for file in glob.glob("downloads/*"):
            os.remove(file)
        for file in glob.glob("processed/*"):
            os.remove(file)
        
        await event.respond(f"**🧹 Cleanup complete!**\n\nRemoved {total_files} temporary files.")
    except Exception as e:
        await event.respond(f"**Error during cleanup:** {str(e)}")


# Error handler
@bot.on(events.MessageEdited)
async def message_edited_handler(event):
    """Handle message edited events to prevent "message not modified" errors"""
    pass  # This is a workaround for MessageNotModifiedError


async def main():
    """Main function to run the bot"""
    print("Starting Video Trimmer Pro Bot...")
    
    try:
        # Attempt to connect to Telegram
        await bot.start(bot_token=BOT_TOKEN)
        print(f"Bot started successfully as @{BOT_UN}")
        
        # Set bot commands
        await bot(events.NewMessage(pattern="setcommands"))
        
        # Run the bot until disconnected
        await bot.run_until_disconnected()
        
    except Exception as e:
        print(f"Error starting bot: {e}")
    finally:
        # Close the client
        await bot.disconnect()
        print("Bot stopped.")


if __name__ == "__main__":
    try:
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
