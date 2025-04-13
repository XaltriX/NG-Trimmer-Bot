import os
import time
import tempfile
import logging
import asyncio
import math
import shutil
from datetime import timedelta
import platform

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from BotFather
TOKEN = "7560987376:AAHX_ODhs4gMDIg5Ib3ijaXVE-1E0uNPvz0"

# Bot configuration
class Config:
    # Telegram standard limits
    BOT_UPLOAD_LIMIT = 50 * 1024 * 1024  # 50MB
    
    # Process timeout (in seconds)
    PROCESS_TIMEOUT = 3600  # 1 hour
    
    # Part duration (in seconds)
    PART_DURATION = 60  # 1 minute
    
    # Chunk size for streaming download (50MB)
    DOWNLOAD_CHUNK_SIZE = 50 * 1024 * 1024
    
    # Maximum compression attempts before giving up
    MAX_COMPRESSION_ATTEMPTS = 3
    
    # FFmpeg path - handles Windows executable naming
    if platform.system() == 'Windows':
        FFMPEG_PATH = "ffmpeg.exe"
        FFPROBE_PATH = "ffprobe.exe"
    else:
        FFMPEG_PATH = "ffmpeg"
        FFPROBE_PATH = "ffprobe"

# Messages
class Messages:
    START = (
        "👋 Welcome to Video Splitter Bot!\n\n"
        "📹 Send me any video, and I'll split it into 1-minute parts.\n\n"
        "🚀 Perfect for sharing long videos on Telegram without Premium!"
    )
    
    HELP = (
        "📖 *Video Splitter Bot Help*\n\n"
        "This bot handles video files by:\n"
        "1️⃣ Processing the video in 50MB chunks\n"
        "2️⃣ Splitting each chunk into 1-minute segments\n"
        "3️⃣ Compressing segments to fit Telegram's limit if needed\n"
        "4️⃣ Sending each part with proper numbering\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/cancel - Cancel an ongoing process\n\n"
        "⚠️ *Note:*\n"
        "- Progress bars show real-time status\n"
        "- You can cancel anytime with /cancel\n"
        "- For best results, send MP4 or MKV format"
    )
    
    DOWNLOADING = "⏳ Starting to process your video..."
    DOWNLOAD_CHUNK = "⏳ Downloading chunk {}: {:.1f}MB of {:.1f}MB ({:.1f}%)"
    PROCESSING = "🔄 Analyzing video chunk..."
    SPLITTING = "✂️ Splitting this chunk into parts..."
    CREATING_PART = "🔨 Creating part {} ... [{} of {}] {}"
    COMPRESSING_PART = "🗜️ Part {} is too large. Compressing (attempt {})..."
    UPLOADING_PART = "📤 Uploading part {} ... [{} of {}]"
    PROCESS_SUCCESS = "✅ Done! All {} parts have been processed successfully."
    PROCESS_TIMEOUT = "⏱️ Process timed out. Please try with a smaller video."
    UNSUPPORTED_FORMAT = "❌ Please send a valid video file (MP4, MKV, MOV, etc)."
    PROCESS_FAILED = "❌ Sorry, an error occurred while processing your video."
    COMPRESSION_FAILED = "❌ Failed to compress part {} to fit Telegram's 50MB limit after multiple attempts."
    CANCEL_PROCESS = "❌ Process cancelled."
    OVERALL_PROGRESS = "\n\n🔄 Overall Progress: {:.1f}% complete"
    FFMPEG_NOT_FOUND = "❌ FFmpeg not found. Please make sure FFmpeg is installed and in your system PATH."
    CHECKING_FFMPEG = "🔍 Checking if FFmpeg is available..."

# Custom progress bar
def get_progress_bar(percentage, length=20):
    filled_length = int(length * percentage / 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {percentage:.1f}%"

# Custom exceptions
class VideoProcessingError(Exception):
    def __init__(self, user_message, admin_message=None):
        self.user_message = user_message
        self.admin_message = admin_message or user_message
        super().__init__(self.user_message)

class VideoProcessor:
    def __init__(self, status_message, context):
        self.status_message = status_message
        self.context = context
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = tempfile.mkdtemp()
        self.last_progress_update = 0
        self.total_parts_sent = 0
        self.estimated_total_parts = 0
        self.total_chunks = 0
        self.current_chunk = 0
    
    async def cleanup(self):
        """Clean up temporary directories"""
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            shutil.rmtree(self.output_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up: {str(e)}")
    
    async def update_status(self, text, force=False):
        """Update status message with rate limiting"""
        try:
            current_time = time.time()
            if force or current_time - self.last_progress_update >= 1.5:  # Update every 1.5 seconds
                await self.status_message.edit_text(text)
                self.last_progress_update = current_time
        except Exception as e:
            logger.warning(f"Failed to update status: {str(e)}")
    
    async def check_ffmpeg(self):
        """Check if FFmpeg is installed and available"""
        await self.update_status(Messages.CHECKING_FFMPEG, force=True)
        
        try:
            # Check FFmpeg
            process = await asyncio.create_subprocess_exec(
                Config.FFMPEG_PATH, "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg not found: {stderr.decode() if stderr else 'No error output'}")
                raise VideoProcessingError(Messages.FFMPEG_NOT_FOUND)
                
            # Check FFprobe
            process = await asyncio.create_subprocess_exec(
                Config.FFPROBE_PATH, "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFprobe not found: {stderr.decode() if stderr else 'No error output'}")
                raise VideoProcessingError(Messages.FFMPEG_NOT_FOUND)
                
        except FileNotFoundError:
            logger.error("FFmpeg/FFprobe executables not found")
            raise VideoProcessingError(Messages.FFMPEG_NOT_FOUND)
    
    async def run_subprocess(self, cmd, timeout=Config.PROCESS_TIMEOUT):
        """Run a subprocess command with timeout and cancellation support"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Set up a task to check for cancellation
            cancel_check_task = asyncio.create_task(self.check_cancellation(process))
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
                cancel_check_task.cancel()
                try:
                    await cancel_check_task
                except asyncio.CancelledError:
                    pass
                
                return stdout, stderr, process.returncode
            except asyncio.TimeoutError:
                logger.error(f"Process timeout for command: {' '.join(cmd)}")
                process.kill()
                raise VideoProcessingError(Messages.PROCESS_TIMEOUT)
                
        except asyncio.CancelledError:
            process.kill()
            raise VideoProcessingError(Messages.CANCEL_PROCESS)
    
    async def check_cancellation(self, process):
        """Check if process should be cancelled"""
        while True:
            await asyncio.sleep(1)
            if not self.context.chat_data.get('active_process', True):
                process.kill()
                raise asyncio.CancelledError()
    
    async def get_video_duration(self, file):
        """Get total video duration to estimate parts"""
        try:
            temp_file = os.path.join(self.temp_dir, "duration_check.mp4")
            
            # Download a small part of the video just to check duration
            await file.download_to_drive(
                custom_path=temp_file,
                read_timeout=60,
                write_timeout=60
            )
            
            # Get duration using ffprobe
            duration_cmd = [
                Config.FFPROBE_PATH, 
                "-v", "error", 
                "-show_entries", "format=duration", 
                "-of", "default=noprint_wrappers=1:nokey=1", 
                temp_file
            ]
            
            stdout, stderr, return_code = await self.run_subprocess(duration_cmd)
            
            if return_code != 0:
                logger.warning(f"Couldn't get duration: {stderr.decode()}")
                return None
            
            try:
                duration = float(stdout.decode().strip())
                self.estimated_total_parts = math.ceil(duration / Config.PART_DURATION)
                return duration
            except (ValueError, UnicodeDecodeError):
                logger.warning("Error parsing duration")
                return None
                
        except Exception as e:
            logger.warning(f"Error getting video duration: {str(e)}")
            return None
    
    async def download_chunk(self, file, offset, chunk_size, total_size, chunk_path):
        """Download a specific chunk of the file"""
        try:
            # Calculate how much to download (handle last chunk)
            size_to_download = min(chunk_size, total_size - offset)
            
            # Stream the download
            downloaded = 0
            
            async with open(chunk_path, 'wb') as f:
                async for data in await file.download_as_chunked_file(
                    chunk_size=1024*1024,  # 1MB chunks for streaming
                    offset=offset,
                    limit=size_to_download
                ):
                    # Check if cancelled
                    if not self.context.chat_data.get('active_process', True):
                        raise VideoProcessingError(Messages.CANCEL_PROCESS)
                    
                    # Write data
                    f.write(data)
                    downloaded += len(data)
                    
                    # Update progress (MB values for user readability)
                    progress = (downloaded / size_to_download) * 100
                    progress_bar = get_progress_bar(progress)
                    
                    chunk_mb = (offset + downloaded) / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    
                    await self.update_status(
                        f"{Messages.DOWNLOAD_CHUNK.format(self.current_chunk, chunk_mb, total_mb, progress)}\n"
                        f"{progress_bar}"
                        f"{Messages.OVERALL_PROGRESS.format((offset + downloaded) / total_size * 100)}"
                    )
            
            return True
            
        except Exception as e:
            logger.error(f"Error downloading chunk: {str(e)}")
            return False
    
    async def get_video_info(self, file_path):
        """Get video information using ffprobe"""
        # Get duration
        duration_cmd = [
            Config.FFPROBE_PATH, 
            "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            file_path
        ]
        
        stdout, stderr, return_code = await self.run_subprocess(duration_cmd)
        
        if return_code != 0:
            logger.error(f"FFprobe error: {stderr.decode()}")
            return {"duration": 60, "width": 640, "height": 360, "bitrate": None}
        
        try:
            duration = float(stdout.decode().strip())
        except (ValueError, UnicodeDecodeError):
            duration = 60
        
        # Get dimensions
        dimensions_cmd = [
            Config.FFPROBE_PATH, 
            "-v", "error", 
            "-select_streams", "v:0", 
            "-show_entries", "stream=width,height", 
            "-of", "csv=s=x:p=0", 
            file_path
        ]
        
        stdout, stderr, return_code = await self.run_subprocess(dimensions_cmd)
        
        if return_code != 0 or not stdout:
            width, height = 640, 360  # Default values
        else:
            try:
                dimensions = stdout.decode().strip().split('x')
                width = int(dimensions[0])
                height = int(dimensions[1])
            except (ValueError, IndexError, UnicodeDecodeError):
                width, height = 640, 360  # Default values
        
        # Get bitrate
        bitrate_cmd = [
            Config.FFPROBE_PATH,
            "-v", "error",
            "-show_entries", "format=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        
        stdout, stderr, return_code = await self.run_subprocess(bitrate_cmd)
        
        if return_code != 0 or not stdout:
            bitrate = None
        else:
            try:
                bitrate = int(stdout.decode().strip())
            except (ValueError, UnicodeDecodeError):
                bitrate = None
        
        return {
            "duration": duration,
            "width": width,
            "height": height,
            "bitrate": bitrate
        }
    
    async def process_chunk(self, chunk_path, start_time_global):
        """Process a single chunk of the video"""
        # Get info about this chunk
        await self.update_status(Messages.PROCESSING)
        video_info = await self.get_video_info(chunk_path)
        
        chunk_duration = video_info["duration"]
        width = video_info["width"]
        height = video_info["height"]
        
        # Calculate how many parts in this chunk
        num_parts = math.ceil(chunk_duration / Config.PART_DURATION)
        await self.update_status(Messages.SPLITTING)
        
        # Process each part
        parts_processed = 0
        for i in range(num_parts):
            # Check if cancelled
            if not self.context.chat_data.get('active_process', True):
                raise VideoProcessingError(Messages.CANCEL_PROCESS)
            
            # Calculate times for this part
            start_time_local = i * Config.PART_DURATION
            end_time_local = min((i + 1) * Config.PART_DURATION, chunk_duration)
            part_duration = end_time_local - start_time_local
            
            # Skip if part is too short (less than 1 second)
            if part_duration < 1:
                continue
            
            # Global part number for progress reporting
            global_part_number = self.total_parts_sent + parts_processed + 1
            
            # Progress bar
            progress = (i / num_parts) * 100
            progress_bar = get_progress_bar(progress)
            
            # Update status
            await self.update_status(
                Messages.CREATING_PART.format(
                    global_part_number, 
                    self.current_chunk, 
                    self.total_chunks,
                    progress_bar
                ) + Messages.OVERALL_PROGRESS.format(
                    ((self.current_chunk - 1) / self.total_chunks * 100) + 
                    (1 / self.total_chunks * progress)
                )
            )
            
            # Output path for this part
            output_path = os.path.join(self.output_dir, f"part_{global_part_number}.mp4")
            
            # Convert start time to format for ffmpeg
            start_str = str(timedelta(seconds=start_time_local)).split('.')[0]
            
            # Create the part with copy mode first for speed
            split_cmd = [
                Config.FFMPEG_PATH,
                '-hide_banner',
                '-ss', start_str,
                '-i', chunk_path,
                '-t', str(part_duration),
                '-c', 'copy',
                '-y',
                output_path
            ]
            
            stdout, stderr, return_code = await self.run_subprocess(split_cmd)
            
            # Check if the file was created successfully
            if return_code != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                logger.error(f"Failed to create part {global_part_number}: {stderr.decode()}")
                # Try again with re-encoding instead of copy
                split_cmd = [
                    Config.FFMPEG_PATH,
                    '-hide_banner',
                    '-ss', start_str,
                    '-i', chunk_path,
                    '-t', str(part_duration),
                    '-c:v', 'libx264',
                    '-preset', 'veryfast',
                    '-c:a', 'aac',
                    '-y',
                    output_path
                ]
                
                stdout, stderr, return_code = await self.run_subprocess(split_cmd)
                
                if return_code != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    logger.error(f"Failed second attempt for part {global_part_number}: {stderr.decode()}")
                    continue
            
            # Check file size and compress if needed
            file_size = os.path.getsize(output_path)
            original_size = file_size
            
            # If file is larger than Telegram's limit, try compressing
            compression_attempt = 0
            while file_size > Config.BOT_UPLOAD_LIMIT and compression_attempt < Config.MAX_COMPRESSION_ATTEMPTS:
                compression_attempt += 1
                
                # Update status
                await self.update_status(Messages.COMPRESSING_PART.format(global_part_number, compression_attempt))
                
                # Calculate target bitrate based on size
                target_bitrate = int((Config.BOT_UPLOAD_LIMIT * 8 * 0.8) / part_duration)
                
                # Don't go too low
                if target_bitrate < 100000:
                    target_bitrate = 100000
                
                # Compressed output path
                compressed_output = os.path.join(self.output_dir, f"comp_part_{global_part_number}_{compression_attempt}.mp4")
                
                # Compression settings - more aggressive with each attempt
                crf = 23 + (compression_attempt * 5)
                preset = "medium" if compression_attempt == 0 else "faster" if compression_attempt == 1 else "veryfast"
                
                # Scale down for more aggressive compression
                scale_factor = 1.0
                if compression_attempt > 1:
                    scale_factor = 0.75 if compression_attempt == 2 else 0.5
                
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                
                # Make width and height even
                new_width = new_width - (new_width % 2)
                new_height = new_height - (new_height % 2)
                
                # Compression command
                compress_cmd = [
                    Config.FFMPEG_PATH,
                    '-i', output_path,
                    '-c:v', 'libx264',
                    '-crf', str(crf),
                    '-preset', preset,
                    '-b:v', f"{target_bitrate}",
                    '-maxrate', f"{target_bitrate * 1.5}",
                    '-bufsize', f"{target_bitrate}",
                ]
                
                # Add scaling if needed
                if scale_factor < 1.0:
                    compress_cmd.extend(['-vf', f'scale={new_width}:{new_height}'])
                
                # Audio settings
                audio_bitrate = "96k" if compression_attempt > 1 else "128k"
                compress_cmd.extend([
                    '-c:a', 'aac',
                    '-b:a', audio_bitrate,
                    '-ac', '2',
                    '-y',
                    compressed_output
                ])
                
                # Run compression
                stdout, stderr, return_code = await self.run_subprocess(compress_cmd)
                
                # Check if compressed file was created
                if return_code == 0 and os.path.exists(compressed_output) and os.path.getsize(compressed_output) > 0:
                    # Update to compressed version
                    old_output = output_path
                    output_path = compressed_output
                    file_size = os.path.getsize(output_path)
                    
                    # Clean up previous version if not original
                    if "comp_part" in old_output:
                        try:
                            os.remove(old_output)
                        except:
                            pass
                else:
                    logger.error(f"Compression attempt {compression_attempt} failed for part {global_part_number}")
            
            # If still too large after compression
            if file_size > Config.BOT_UPLOAD_LIMIT:
                await self.update_status(Messages.COMPRESSION_FAILED.format(global_part_number))
                continue
            
            # Prepare to send video
            await self.update_status(
                Messages.UPLOADING_PART.format(
                    global_part_number, 
                    self.current_chunk, 
                    self.total_chunks
                ) + Messages.OVERALL_PROGRESS.format(
                    ((self.current_chunk - 1) / self.total_chunks * 100) + 
                    (1 / self.total_chunks * progress)
                )
            )
            
            # Format global timestamp for caption (start time since beginning of video)
            global_timestamp = str(timedelta(seconds=start_time_global + start_time_local)).split('.')[0]
            
            # Compression info for caption
            compression_info = ""
            if "comp_part" in output_path:
                compression_ratio = (1 - (file_size / original_size)) * 100
                compression_info = f"\n💾 Compressed: {file_size / 1024 / 1024:.1f}MB ({compression_ratio:.1f}% reduction)"
            
            # Send the video part
            try:
                with open(output_path, 'rb') as video_file:
                    # Send with appropriate caption
                    await self.status_message.reply_video(
                        video=video_file,
                        caption=f"Part {global_part_number} [Time: {global_timestamp}]{compression_info}",
                        width=width,
                        height=height,
                        duration=int(part_duration),
                        supports_streaming=True
                    )
                
                parts_processed += 1
                
                # Clean up part to save space
                try:
                    os.remove(output_path)
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"Error sending part {global_part_number}: {str(e)}")
                await self.update_status(f"❌ Failed to send part {global_part_number}")
        
        # Return number of parts successfully processed
        return parts_processed
    
    async def process_video_in_chunks(self, file, file_size):
        """Process a video in 50MB chunks"""
        # First, check if FFmpeg is installed
        await self.check_ffmpeg()
        
        # Try to get total duration to estimate parts
        total_duration = await self.get_video_duration(file)
        
        # Calculate number of chunks needed
        self.total_chunks = math.ceil(file_size / Config.DOWNLOAD_CHUNK_SIZE)
        
        # Process each chunk
        offset = 0
        start_time_offset = 0
        
        for chunk_index in range(self.total_chunks):
            # Check if canceled
            if not self.context.chat_data.get('active_process', True):
                raise VideoProcessingError(Messages.CANCEL_PROCESS)
            
            self.current_chunk = chunk_index + 1
            
            # Chunk path
            chunk_path = os.path.join(self.temp_dir, f"chunk_{chunk_index}.mp4")
            
            # Download this chunk
            success = await self.download_chunk(
                file, offset, Config.DOWNLOAD_CHUNK_SIZE, file_size, chunk_path
            )
            
            if not success:
                logger.error(f"Failed to download chunk {chunk_index}")
                continue
            
            # Process this chunk
            parts_in_chunk = await self.process_chunk(chunk_path, start_time_offset)
            
            # Update counters
            self.total_parts_sent += parts_in_chunk
            
            # Get info for this chunk to calculate next start time
            chunk_info = await self.get_video_info(chunk_path)
            start_time_offset += chunk_info["duration"]
            
            # Clean up chunk file
            try:
                os.remove(chunk_path)
            except:
                pass
            
            # Move to next chunk
            offset += Config.DOWNLOAD_CHUNK_SIZE
            
            # Stop if we've reached end of file
            if offset >= file_size:
                break
        
        # Final success message
        if self.total_parts_sent > 0:
            await self.status_message.edit_text(Messages.PROCESS_SUCCESS.format(self.total_parts_sent))
        else:
            raise VideoProcessingError(Messages.PROCESS_FAILED)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(Messages.START)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(Messages.HELP, parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the current operation."""
    if context.chat_data.get('active_process', False):
        context.chat_data['active_process'] = False
        await update.message.reply_text(Messages.CANCEL_PROCESS)
    else:
        await update.message.reply_text("No active process to cancel.")

async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process the video sent by the user."""
    # Check if the message contains a video or video document
    if not update.message.video and not update.message.document:
        await update.message.reply_text(Messages.UNSUPPORTED_FORMAT)
        return
    
    # Check if document is actually a video
    if update.message.document:
        mime_type = update.message.document.mime_type
        if not mime_type or not mime_type.startswith('video/'):
            await update.message.reply_text(Messages.UNSUPPORTED_FORMAT)
            return
    
    # Check if already processing
    if context.chat_data.get('active_process', False):
        await update.message.reply_text("⚠️ I'm already processing a video. Please wait or use /cancel to stop the current operation.")
        return
    
    # Set active process flag
    context.chat_data['active_process'] = True
    
    # Status message
    status_message = await update.message.reply_text(Messages.DOWNLOADING)
    
    # Create processor
    processor = VideoProcessor(status_message, context)
    
    try:
        # Get file info
        if update.message.video:
            file = await update.message.video.get_file()
            file_size = update.message.video.file_size
        else:
            file = await update.message.document.get_file()
            file_size = update.message.document.file_size
        
        # Process video in chunks
        await processor.process_video_in_chunks(file, file_size)
        
    except VideoProcessingError as e:
        await status_message.edit_text(e.user_message)
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}", exc_info=True)
        await status_message.edit_text(
            f"{Messages.PROCESS_FAILED}\n\nError: {escape_markdown(str(e)[:100], version=2)}\n\nPlease try with a different video."
        )
    finally:
        # Clean up
        context.chat_data['active_process'] = False
        await processor.cleanup()

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, process_video))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()
