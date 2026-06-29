import os
import sys
import time
import platform
import psutil
from datetime import datetime
import utils

# Track when the module/process started
BOT_STARTUP_TIME = datetime.now()

def get_bot_uptime() -> float:
    """Return bot uptime in seconds."""
    return (datetime.now() - BOT_STARTUP_TIME).total_seconds()

def get_system_uptime() -> float:
    """Return system boot time uptime in seconds."""
    try:
        boot_time = psutil.boot_time()
        return time.time() - boot_time
    except Exception:
        return 0.0

def get_server_stats() -> dict:
    """Gather server utilization stats."""
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.1)
    
    # RAM
    ram = psutil.virtual_memory()
    ram_total = ram.total
    ram_used = ram.used
    ram_percent = ram.percent
    
    # Disk (check workspace directory disk space)
    try:
        disk = psutil.disk_usage('.')
        disk_total = disk.total
        disk_used = disk.used
        disk_percent = disk.percent
    except Exception:
        disk_total = 0
        disk_used = 0
        disk_percent = 0.0

    return {
        "cpu_percent": cpu_percent,
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_percent": ram_percent,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_percent": disk_percent,
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python_version": platform.python_version(),
        "bot_uptime": get_bot_uptime(),
        "system_uptime": get_system_uptime()
    }

def format_server_status() -> str:
    """Format the server utilization stats into a readable string."""
    stats = get_server_stats()
    
    cpu_bar = "█" * int(stats["cpu_percent"] / 10) + "░" * (10 - int(stats["cpu_percent"] / 10))
    ram_bar = "█" * int(stats["ram_percent"] / 10) + "░" * (10 - int(stats["ram_percent"] / 10))
    disk_bar = "█" * int(stats["disk_percent"] / 10) + "░" * (10 - int(stats["disk_percent"] / 10))

    bot_uptime_str = utils.format_duration(stats["bot_uptime"])
    sys_uptime_str = utils.format_duration(stats["system_uptime"])

    ram_total_str = utils.format_bytes(stats["ram_total"])
    ram_used_str = utils.format_bytes(stats["ram_used"])
    disk_total_str = utils.format_bytes(stats["disk_total"])
    disk_used_str = utils.format_bytes(stats["disk_used"])

    return (
        f"🖥️ **Status Server**\n"
        f"• **OS**: {stats['platform']} {stats['platform_release']}\n"
        f"• **Python**: {stats['python_version']}\n"
        f"• **Bot Uptime**: `{bot_uptime_str}`\n"
        f"• **Server Uptime**: `{sys_uptime_str}`\n\n"
        f"📊 **Resource Metrics**\n"
        f"• **CPU Load**: `[{cpu_bar}] {stats['cpu_percent']}%`\n"
        f"• **RAM Usage**: `[{ram_bar}] {stats['ram_percent']}%` ({ram_used_str} / {ram_total_str})\n"
        f"• **Disk Usage**: `[{disk_bar}] {stats['disk_percent']}%` ({disk_used_str} / {disk_total_str})"
    )
