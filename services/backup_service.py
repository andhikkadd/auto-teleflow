import os
import shutil
import zipfile
import subprocess
import logging
from datetime import datetime
from pathlib import Path
import config

logger = logging.getLogger("BackupService")

class BackupService:
    @staticmethod
    def is_gpg_available() -> bool:
        """Check if gpg command line tool is available on the system."""
        try:
            subprocess.run(["gpg", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    @staticmethod
    async def create_backup() -> list[str]:
        """
        Creates a single backup archive for the entire bot ecosystem.
        Returns a list of absolute paths to the generated backup files.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Define base directories relative to this file
        service_file_path = Path(__file__).resolve()
        project_root = service_file_path.parent.parent
        
        backups_dir = project_root / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        
        backup_files = []
        
        # 1. CREATE BOT ECOSYSTEM BACKUP
        bot_zip_path = backups_dir / f"backup_bot_{timestamp}.zip"
        try:
            with zipfile.ZipFile(bot_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add source files from root
                bot_files = [
                    "main.py", "config.py", "database.py", "telegram_client.py",
                    "commands.py", "scheduler.py", "web_panel.py",
                    "server_status.py", "utils.py", "requirements.txt", "README.md", "runner.py"
                ]
                for f_name in bot_files:
                    f_path = project_root / f_name
                    if f_path.exists():
                        zipf.write(str(f_path), arcname=f_name)
                
                # Add services
                services_dir = project_root / "services"
                if services_dir.is_dir():
                    for svc_file in services_dir.glob("*.py"):
                        zipf.write(str(svc_file), arcname=os.path.join("services", svc_file.name))
                        
                # Add templates
                templates_dir = project_root / "templates"
                if templates_dir.is_dir():
                    for t_file in templates_dir.rglob("*"):
                        if t_file.is_file():
                            zipf.write(str(t_file), arcname=os.path.join("templates", str(t_file.relative_to(templates_dir))))
                            
                # Add database
                if os.path.exists(config.DATABASE_PATH):
                    zipf.write(config.DATABASE_PATH, arcname="data/bot.db")
                    
                # Add sessions
                sess_dir = project_root / "sessions"
                if sess_dir.is_dir():
                    for session_file in sess_dir.glob("*.session"):
                        zipf.write(str(session_file), arcname=os.path.join("sessions", session_file.name))
                    for journal_file in sess_dir.glob("*.session-journal"):
                        zipf.write(str(journal_file), arcname=os.path.join("sessions", journal_file.name))
                        
                # Add env
                camp_env = project_root / ".env"
                if camp_env.exists():
                    zipf.write(str(camp_env), arcname=".env")
                    
            logger.info(f"Ecosystem backup created: {bot_zip_path}")
            backup_files.append(str(bot_zip_path.resolve()))
        except Exception as e:
            logger.error(f"Failed to create bot backup: {e}", exc_info=True)
            
        # Encrypt with GPG if available and allowed
        gpg_ok = BackupService.is_gpg_available()
        from utils import sanitize_logs
        
        final_files = []
        for zip_p in backup_files:
            zip_path = Path(zip_p)
            if gpg_ok:
                if not config.BACKUP_PASSWORD:
                    if zip_path.exists():
                        zip_path.unlink()
                    raise ValueError("GPG is available but BACKUP_PASSWORD is not set in .env")
                
                gpg_path = zip_path.with_suffix(zip_path.suffix + ".gpg")
                try:
                    process = subprocess.Popen(
                        [
                            "gpg", "--symmetric", "--batch", "--yes",
                            "--passphrase-fd", "0", "--cipher-algo", "AES256",
                            "-o", str(gpg_path), str(zip_path)
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    stdout, stderr = process.communicate(input=config.BACKUP_PASSWORD)
                    if process.returncode != 0:
                        raise RuntimeError(f"GPG encryption failed: {sanitize_logs(stderr)}")
                    
                    if zip_path.exists():
                        zip_path.unlink()
                    final_files.append(str(gpg_path.resolve()))
                except Exception as e:
                    if gpg_path.exists():
                        gpg_path.unlink()
                    if zip_path.exists():
                        zip_path.unlink()
                    raise RuntimeError(f"GPG Encryption error: {sanitize_logs(str(e))}")
            else:
                if config.ALLOW_UNENCRYPTED_BACKUP:
                    final_files.append(str(zip_path.resolve()))
                else:
                    if zip_path.exists():
                        zip_path.unlink()
                    raise RuntimeError(
                        "GPG is not available and ALLOW_UNENCRYPTED_BACKUP=false. "
                        "Secure backup cannot be generated."
                    )
        return final_files

    @staticmethod
    def clean_backup_file(file_path: str):
        """Remove the backup file from the disk if DELETE_LOCAL_BACKUP_AFTER_SEND is enabled."""
        if not config.DELETE_LOCAL_BACKUP_AFTER_SEND:
            logger.info(f"Local backup deletion skipped as DELETE_LOCAL_BACKUP_AFTER_SEND is false: {file_path}")
            return
            
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info(f"Temporary backup file deleted from disk: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete backup file {file_path}: {e}")

backup_svc = BackupService()
