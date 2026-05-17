import os
import re
import time
import logging
import paramiko

logger = logging.getLogger("pipeline.sftp")

def find_latest_matching_file(file_attrs, pattern, safe_age):
    """Find the newest file matching pattern that is older than safe_age seconds."""
    now = time.time()
    candidates = [
        f for f in file_attrs
        if pattern.match(f.filename) and (now - f.st_mtime) >= safe_age
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.st_mtime)

class SFTPClient:
    def __init__(self, settings):
        self._settings = settings
        self._transport = None
        self._sftp = None

    def connect(self):
        self._transport = paramiko.Transport((self._settings.SFTP_HOST, self._settings.SFTP_PORT))
        self._transport.set_keepalive(30)
        self._transport.connect(username=self._settings.SFTP_USERNAME, password=self._settings.SFTP_PASSWORD)
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        # Change to remote directory if configured
        remote_dir = getattr(self._settings, "SFTP_REMOTE_DIR", "")
        if remote_dir:
            self._sftp.chdir(remote_dir)
            logger.info(f"SFTP connected, working directory: {remote_dir}")
        else:
            logger.info("SFTP connected")

    def download_latest(self):
        """Download latest matching Excel file. Returns (local_path, filename) or (None, None)."""
        files = self._sftp.listdir_attr()
        pattern = re.compile(re.escape(self._settings.SFTP_FILE_PATTERN).replace(r"\*", ".*") + "$", re.IGNORECASE)
        latest = find_latest_matching_file(files, pattern, self._settings.SFTP_SAFE_AGE_SECONDS)
        if not latest:
            logger.warning("No matching Excel file found on SFTP")
            return None, None
        local_dir = self._settings.DOWNLOAD_DIR
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, latest.filename)
        for attempt in range(1, 4):
            try:
                self._sftp.get(latest.filename, local_path)
                logger.info(f"Downloaded {latest.filename} to {local_path}")
                return local_path, latest.filename
            except Exception as e:
                logger.warning(f"Download attempt {attempt} failed: {e}")
                if attempt == 3:
                    raise
                time.sleep(3)
        return None, None

    def delete_file(self, filename):
        """Delete a file from the current SFTP working directory."""
        try:
            self._sftp.remove(filename)
            logger.info(f"Deleted {filename} from SFTP")
        except Exception as e:
            logger.warning(f"Failed to delete {filename} from SFTP: {e}")

    def close(self):
        try:
            if self._sftp: self._sftp.close()
        except: pass
        try:
            if self._transport: self._transport.close()
        except: pass
        logger.info("SFTP connection closed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
