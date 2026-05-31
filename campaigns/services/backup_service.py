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
    async def create_backup() -> str:
        """
        Creates a backup archive.
        Returns the absolute path to the generated backup file (either GPG or ZIP).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_zip_path = Path(f"backups/temp_backup_{timestamp}.zip")
        
        # Define files to package
        source_files = [
            "main.py", "config.py", "database.py", "telegram_client.py",
            "commands.py", "scheduler.py", "web_panel.py",
            "server_status.py", "utils.py", "requirements.txt", "README.md",
            "DEPLOYMENT.md", "DEPLOY_PTERODACTYL.md", "GITHUB_WORKFLOW.md",
            "SECURITY.md", "CHANGELOG.md", ".env.example"
        ]
        
        # Include services files
        services_dir = Path("services")
        if services_dir.is_dir():
            for svc_file in services_dir.glob("*.py"):
                source_files.append(str(svc_file))
                
        logger.info("Starting backup archiving process...")
        
        # Ensure backups folder exists
        Path("backups").mkdir(parents=True, exist_ok=True)
        
        try:
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add source files
                for f_name in source_files:
                    if os.path.exists(f_name):
                        zipf.write(f_name)
                        
                # Add database
                if os.path.exists(config.DATABASE_PATH):
                    zipf.write(config.DATABASE_PATH)
                    
                # Add sessions folder
                sess_dir = Path("sessions")
                if sess_dir.is_dir():
                    for session_file in sess_dir.glob("*.session"):
                        zipf.write(str(session_file))
                    for journal_file in sess_dir.glob("*.session-journal"):
                        zipf.write(str(journal_file))

                # Add docs folder
                docs_dir = Path("docs")
                if docs_dir.is_dir():
                    for doc_file in docs_dir.rglob("*"):
                        if doc_file.is_file():
                            zipf.write(str(doc_file))

                # Add templates folder
                templates_dir = Path("templates")
                if templates_dir.is_dir():
                    for t_file in templates_dir.rglob("*"):
                        if t_file.is_file():
                            zipf.write(str(t_file))

                # Add static folder
                static_dir = Path("static")
                if static_dir.is_dir():
                    for s_file in static_dir.rglob("*"):
                        if s_file.is_file():
                            zipf.write(str(s_file))

                # Include .env ONLY if explicitly configured, but sanitize out BACKUP_PASSWORD & other secrets
                if config.BACKUP_INCLUDE_ENV and os.path.exists(".env"):
                    temp_env_path = Path("backups/temp_env")
                    try:
                        with open(".env", "r", encoding="utf-8") as f_in, open(temp_env_path, "w", encoding="utf-8") as f_out:
                            for line in f_in:
                                stripped = line.strip()
                                # Redact highly critical secrets before packing
                                if stripped.startswith("BACKUP_PASSWORD="):
                                    f_out.write("BACKUP_PASSWORD=***REMOVED_FOR_SECURITY***\n")
                                elif stripped.startswith("WEB_ADMIN_PASSWORD="):
                                    f_out.write("WEB_ADMIN_PASSWORD=***REMOVED_FOR_SECURITY***\n")
                                elif stripped.startswith("WEB_SESSION_SECRET="):
                                    f_out.write("WEB_SESSION_SECRET=***REMOVED_FOR_SECURITY***\n")
                                elif stripped.startswith("API_HASH="):
                                    f_out.write("API_HASH=***REMOVED_FOR_SECURITY***\n")
                                else:
                                    f_out.write(line)
                        zipf.write(temp_env_path, arcname=".env")
                        logger.info("Sanitized .env file included in backup.")
                    finally:
                        if temp_env_path.exists():
                            temp_env_path.unlink()
                    
            logger.info(f"Temporary zip archive created: {temp_zip_path}")
            
        except Exception as e:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
            raise RuntimeError(f"Failed to create ZIP archive: {e}")

        # Check for GPG encryption
        gpg_ok = BackupService.is_gpg_available()
        from utils import sanitize_logs
        
        if gpg_ok:
            if not config.BACKUP_PASSWORD:
                if temp_zip_path.exists():
                    temp_zip_path.unlink()
                raise ValueError("GPG is available but BACKUP_PASSWORD is not set in .env")

            gpg_output_path = Path(f"backups/backup_{timestamp}.zip.gpg")
            logger.info("GPG is available. Encrypting archive with AES256...")
            
            try:
                process = subprocess.Popen(
                    [
                        "gpg", "--symmetric", "--batch", "--yes",
                        "--passphrase-fd", "0", "--cipher-algo", "AES256",
                        "-o", str(gpg_output_path), str(temp_zip_path)
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Send password via stdin safely
                stdout, stderr = process.communicate(input=config.BACKUP_PASSWORD)
                
                if process.returncode != 0:
                    sanitized_err = sanitize_logs(stderr)
                    raise RuntimeError(f"GPG encryption failed: {sanitized_err}")
                    
                logger.info(f"Archive encrypted successfully: {gpg_output_path}")
                
                # Clean up unencrypted temporary zip
                if temp_zip_path.exists():
                    temp_zip_path.unlink()
                    
                return str(gpg_output_path.resolve())
                
            except Exception as e:
                if gpg_output_path.exists():
                    gpg_output_path.unlink()
                if temp_zip_path.exists():
                    temp_zip_path.unlink()
                raise RuntimeError(f"GPG Encryption process error: {sanitize_logs(str(e))}")
                
        else:
            # Fallback if GPG is not available
            logger.warning("GPG is NOT available on this system.")
            if config.ALLOW_UNENCRYPTED_BACKUP:
                fallback_zip_path = Path(f"backups/backup_{timestamp}.zip")
                shutil.move(str(temp_zip_path), str(fallback_zip_path))
                logger.warning(f"Unencrypted backup allowed. Saved as: {fallback_zip_path}")
                return str(fallback_zip_path.resolve())
            else:
                if temp_zip_path.exists():
                    temp_zip_path.unlink()
                raise RuntimeError(
                    "GPG is not available and ALLOW_UNENCRYPTED_BACKUP=false. "
                    "Secure backup cannot be generated."
                )

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
