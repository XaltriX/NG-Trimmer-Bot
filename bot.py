import os
import time
import asyncio
import math
from datetime import datetime as dt

from telethon import TelegramClient, events, Button
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from telethon.tl.types import DocumentAttributeVideo
from telethon.utils import get_display_name

# Initialize the bot
API_ID = 24955235  # Replace with your API ID
API_HASH = "f317b3f7bbe390346d8b46868cff0de8"  # Replace with your API hash
BOT_TOKEN = "7560987376:AAFNJmERp1WT3WgBwkaKV6lqjPxUZ5ZKzak"
BOT_UN = "VideoTrimmerProBot"  # Your bot username

# Create the client
bot = TelegramClient('VideoTrimmerBot', API_ID, API_HASH)

# Support and info
SUPPORT_LINK = "https://t.me/your_support_channel"
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
        import subprocess
        import json

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
        import shutil
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
        import shutil
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
        import glob
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
    """Handle selection of split mode"""
    user_id = event.sender_id
    
    # Check if user has an active video
    if user_id not in user_states or not user_states[user_id].original_message:
        await event.answer("Please send a video first!", alert=True)
        return
    
    await event.answer("Starting split operation...")
    
    # Create confirmation message with warning about large videos
    confirmation = (
        "**🪓 SPLIT MODE Selected**\n\n"
        "This will split your video into 1-minute segments.\n\n"
        "⚠️ **Warning:** For large videos, this may produce many files.\n\n"
        "Do you want to proceed?"
    )
    
    buttons = [
        [
            Button.inline("✅ Yes, split my video", b"confirm_split"),
            Button.inline("❌ Cancel", b"cancel_split")
        ]
    ]
    
    await event.edit(confirmation, buttons=buttons)


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
    progress_message = await event.respond("**Initializing trim operation...**")
    
    try:
        # Download the video
        await progress_message.edit("**Preparing to download...**")
        await fast_download(input_file, original_message, bot, progress_message)
        
        # Check if file exists after download
        if not os.path.exists(input_file):
            await progress_message.edit("❌ **Download failed. File not found.**")
            return
            
        # Process the video
        await progress_message.edit(
            f"**Trimming video from `{start_time}` to `{end_time}`...**\n"
            f"This may take some time depending on the video size."
        )
        
        try:
            await execute_ffmpeg(input_file, output_file, start_time, end_time)
        except Exception as e:
            await progress_message.edit(f"❌ **Trimming failed:** {str(e)}")
            # Clean up
            if os.path.exists(input_file):
                try:
                    os.remove(input_file)
                except:
                    pass
            return
        
        # Upload the trimmed video
        caption = (
            f"**✂️ TRIMMED VIDEO**\n"
            f"⏱️ From: `{start_time}` To: `{end_time}`\n"
            f"🤖 Trimmed by @{BOT_UN}"
        )
        
        try:
            await fast_upload(output_file, bot, progress_message, caption)
            await progress_message.edit("**✅ Video trimmed and uploaded successfully!**")
        except Exception as e:
            await progress_message.edit(f"❌ **Upload failed:** {str(e)}\n\nPlease try again or contact support.")
    except Exception as e:
        await progress_message.edit(
            f"❌ **An error occurred:**\n`{str(e)}`\n\n"
            f"Please try again or contact [support]({SUPPORT_LINK}).",
            link_preview=False
        )
    finally:
        # Clean up
        if os.path.exists(input_file):
            try:
                os.remove(input_file)
            except:
                pass
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass


async def split_video(progress_message, original_message):
    """Process video splitting into 1-minute segments"""
    user_id = progress_message.sender_id if hasattr(progress_message, "sender_id") else 0
    
    # Create unique filenames
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    input_file = os.path.abspath(f"downloads/input_{user_id}_{timestamp}")
    output_pattern = os.path.abspath(f"processed/split_{user_id}_{timestamp}_%03d")
    
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
        # Download the video
        await progress_message.edit("**Preparing to download...**")
        await fast_download(input_file, original_message, bot, progress_message)
        
        # Check if file exists after download
        if not os.path.exists(input_file):
            await progress_message.edit("❌ **Download failed. File not found.**")
            return
            
        # Get video duration for estimation
        metadata = await get_video_metadata(input_file)
        duration = metadata.get("duration", 0)
        estimated_parts = math.ceil(duration / 60)
        
        # Process the video
        await progress_message.edit(
            f"**Splitting video into 1-minute segments...**\n"
            f"Estimated number of parts: **{estimated_parts}**\n"
            f"This may take some time depending on the video size."
        )
        
        try:
            # Set segment duration to 60 seconds (1 minute)
            segment_files = await split_video_into_segments(input_file, output_pattern, 60)
            total_segments = len(segment_files)
            
            await progress_message.edit(
                f"**🎬 Video split into {total_segments} parts**\n"
                f"Starting upload of all segments..."
            )
            
            # Upload each segment
            for i, segment_file in enumerate(segment_files, 1):
                # Update progress
                await progress_message.edit(
                    f"**Uploading segment {i}/{total_segments}...**"
                )
                
                # Prepare caption
                caption = (
                    f"**🪓 SPLIT VIDEO - PART {i}/{total_segments}**\n"
                    f"⏱️ Duration: ~1 minute\n"
                    f"🤖 Split by @{BOT_UN}"
                )
                
                # Upload the segment
                try:
                    await fast_upload(segment_file, bot, progress_message, caption)
                except Exception as e:
                    await progress_message.edit(f"❌ **Failed to upload part {i}:** {str(e)}")
                    continue
                
                # Delete the segment file after upload
                try:
                    os.remove(segment_file)
                except:
                    pass
            
            await progress_message.edit("**✅ Video split and all parts uploaded successfully!**")
        except Exception as e:
            await progress_message.edit(f"❌ **Splitting failed:** {str(e)}")
    except Exception as e:
        await progress_message.edit(
            f"❌ **An error occurred:**\n`{str(e)}`\n\n"
            f"Please try again or contact [support]({SUPPORT_LINK}).",
            link_preview=False
        )
    finally:
        # Clean up
        if os.path.exists(input_file):
            try:
                os.remove(input_file)
            except:
                pass
        
        # Clean up any remaining segment files
        import glob
        segment_files = glob.glob(output_pattern.replace("%03d", "*"))
        for file in segment_files:
            try:
                os.remove(file)
            except:
                pass


# Additional function to handle custom split durations
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


async def split_video_custom_duration(progress_message, original_message, segment_duration):
    """Process video splitting into segments of custom duration"""
    user_id = progress_message.sender_id if hasattr(progress_message, "sender_id") else 0
    
    # Create unique filenames
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    input_file = os.path.abspath(f"downloads/input_{user_id}_{timestamp}")
    output_pattern = os.path.abspath(f"processed/split_{user_id}_{timestamp}_%03d")
    
    # Determine file extension (same code as in split_video function)
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
        # Download the video
        await progress_message.edit("**Preparing to download...**")
        await fast_download(input_file, original_message, bot, progress_message)
        
        # Check if file exists after download
        if not os.path.exists(input_file):
            await progress_message.edit("❌ **Download failed. File not found.**")
            return
            
        # Get video duration for estimation
        metadata = await get_video_metadata(input_file)
        duration = metadata.get("duration", 0)
        estimated_parts = math.ceil(duration / segment_duration)
        
        # Format segment duration for display
        if segment_duration >= 60:
            minutes = segment_duration // 60
            seconds = segment_duration % 60
            duration_str = f"{minutes} minute{'s' if minutes > 1 else ''}"
            if seconds > 0:
                duration_str += f" {seconds} second{'s' if seconds > 1 else ''}"
        else:
            duration_str = f"{segment_duration} second{'s' if segment_duration > 1 else ''}"
        
        # Process the video
        await progress_message.edit(
            f"**Splitting video into {duration_str} segments...**\n"
            f"Estimated number of parts: **{estimated_parts}**\n"
            f"This may take some time depending on the video size."
        )
        
        try:
            # Use the custom segment duration
            segment_files = await split_video_into_segments(input_file, output_pattern, segment_duration)
            total_segments = len(segment_files)
            
            await progress_message.edit(
                f"**🎬 Video split into {total_segments} parts**\n"
                f"Starting upload of all segments..."
            )
            
            # Upload each segment
            for i, segment_file in enumerate(segment_files, 1):
                # Update progress
                await progress_message.edit(
                    f"**Uploading segment {i}/{total_segments}...**"
                )
                
                # Prepare caption
                caption = (
                    f"**🪓 SPLIT VIDEO - PART {i}/{total_segments}**\n"
                    f"⏱️ Duration: ~{duration_str}\n"
                    f"🤖 Split by @{BOT_UN}"
                )
                
                # Upload the segment
                try:
                    await fast_upload(segment_file, bot, progress_message, caption)
                except Exception as e:
                    await progress_message.edit(f"❌ **Failed to upload part {i}:** {str(e)}")
                    continue
                
                # Delete the segment file after upload
                try:
                    os.remove(segment_file)
                except:
                    pass
            
            await progress_message.edit("**✅ Video split and all parts uploaded successfully!**")
        except Exception as e:
            await progress_message.edit(f"❌ **Splitting failed:** {str(e)}")
    except Exception as e:
        await progress_message.edit(
            f"❌ **An error occurred:**\n`{str(e)}`\n\n"
            f"Please try again or contact [support]({SUPPORT_LINK}).",
            link_preview=False
        )
    finally:
        # Clean up
        if os.path.exists(input_file):
            try:
                os.remove(input_file)
            except:
                pass
        
        # Clean up any remaining segment files
        import glob
        segment_files = glob.glob(output_pattern.replace("%03d", "*"))
        for file in segment_files:
            try:
                os.remove(file)
            except:
                pass


# Enhanced callback for split mode with additional options
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


# Add command to show help
@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    """Handle /help command"""
    help_text = (
        "**📋 Video Trimmer Bot Help**\n\n"
        "**Available Commands:**\n"
        "• `/start` - Start the bot and see welcome message\n"
        "• `/help` - Show this help message\n\n"
        
        "**How to Trim a Video:**\n"
        "1. Send any video file to the bot\n"
        "2. Select 'Trim Video' option\n"
        "3. Enter start and end times (format: `00:30 02:15`)\n\n"
        
        "**How to Split a Video:**\n"
        "1. Send any video file to the bot\n"
        "2. Select 'Split into 1-Min Parts' option\n"
        "3. Confirm or select custom duration\n"
        "4. Wait for the bot to process and upload all parts\n\n"
        
        "**Time Format:**\n"
        "• For times less than 1 hour: `MM:SS`\n"
        "• For times more than 1 hour: `HH:MM:SS`\n\n"
        
        "**Examples:**\n"
        "• `00:30 02:15` - Trim from 30 seconds to 2 minutes 15 seconds\n"
        "• `01:25:00 01:35:30` - Trim from 1 hour 25 minutes to 1 hour 35 minutes 30 seconds\n\n"
        
        "If you encounter any issues, please contact our support."
    )
    
    buttons = [
        [Button.url("Support Channel", SUPPORT_LINK)]
    ]
    
    await event.respond(help_text, buttons=buttons)


# Set up the bot
async def main():
    # Start the bot
    print("Starting bot...")
    await bot.start(bot_token=BOT_TOKEN)
    print("Bot started!")
    
    # Set bot commands
    from telethon.tl.functions.bots import SetBotCommandsRequest
    from telethon.tl.types import BotCommand
    
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="help", description="Show help information")
    ]
    
    try:
        await bot(SetBotCommandsRequest(
            scope=telethon.tl.types.BotCommandScopeDefault(),
            lang_code="",
            commands=commands
        ))
        print("Bot commands set successfully")
    except Exception as e:
        print(f"Failed to set bot commands: {e}")
    
    # Run the bot until disconnected
    await bot.run_until_disconnected()

# Run the bot
if __name__ == "__main__":
    asyncio.run(main())
